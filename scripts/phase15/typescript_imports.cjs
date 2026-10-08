/* Extract executable imports with the repository's pinned TypeScript parser. */
const fs = require("node:fs");
const ts = require("../../apps/web/node_modules/typescript");
const inputs = JSON.parse(fs.readFileSync(0, "utf8"));
const results = inputs.map(({ path, source }) => {
  const tree = ts.createSourceFile(path, source, ts.ScriptTarget.Latest, true);
  const modules = [];
  const errors = tree.parseDiagnostics.map((diagnostic) =>
    ts.flattenDiagnosticMessageText(diagnostic.messageText, " "));
  // Bind only this source file. Symbol identity distinguishes loader aliases
  // from unrelated local objects/parameters with the same spelling. No module
  // resolution, user code execution or dependency installation takes place.
  const host = {
    getSourceFile: name => name === path ? tree : undefined,
    getDefaultLibFileName: () => "", writeFile: () => {},
    getCurrentDirectory: () => "", getDirectories: () => [],
    fileExists: name => name === path, readFile: name => name === path ? source : undefined,
    getCanonicalFileName: name => name, useCaseSensitiveFileNames: () => true,
    getNewLine: () => "\n",
  };
  const program = ts.createProgram([path], { noLib: true, noResolve: true }, host);
  const checker = program.getTypeChecker();
  const assignments = new Map();
  function recordAssignments(node) {
    if (ts.isBinaryExpression(node) && [ts.SyntaxKind.EqualsToken, ts.SyntaxKind.BarBarEqualsToken,
      ts.SyntaxKind.AmpersandAmpersandEqualsToken, ts.SyntaxKind.QuestionQuestionEqualsToken].includes(node.operatorToken.kind)
      && ts.isIdentifier(node.left)) {
      const symbol = checker.getSymbolAtLocation(node.left);
      if (symbol) {
        if (!assignments.has(symbol)) assignments.set(symbol, []);
        assignments.get(symbol).push(node.right);
      }
    }
    ts.forEachChild(node, recordAssignments);
  }
  recordAssignments(tree);
  function constantString(node) {
    if (!node) return null;
    if (ts.isStringLiteral(node) || ts.isNoSubstitutionTemplateLiteral(node)) return node.text;
    if (ts.isBinaryExpression(node) && node.operatorToken.kind === ts.SyntaxKind.PlusToken) {
      const left = constantString(node.left), right = constantString(node.right);
      return left !== null && right !== null ? left + right : null;
    }
    if (ts.isParenthesizedExpression(node)) return constantString(node.expression);
    return null;
  }
  const nodeModules = new Set(["module", "node:module"]);
  function unwrap(node) {
    while (node && (ts.isParenthesizedExpression(node) || ts.isAsExpression(node) ||
      ts.isTypeAssertionExpression(node) || ts.isNonNullExpression(node) || ts.isSatisfiesExpression(node)))
      node = node.expression;
    return node;
  }
  function property(node) {
    return ts.isPropertyAccessExpression(node) ? node.name.text : constantString(node.argumentExpression);
  }
  function member(base, name) {
    if (base === "commonjs-module") {
      if (name === "require") return "loader";
      if (name === "constructor") return "module-constructor";
      return name === null ? "unknown-loader" : null;
    }
    if (base === "module-namespace" || base === "module-constructor") {
      if (name === "_load") return "loader";
      if (name === "createRequire") return "factory";
      if (name === "Module" || (base === "module-namespace" && name === "default")) return "module-constructor";
      if (base === "module-constructor" && name === "prototype") return "commonjs-module";
      return name === null ? "unknown-loader" : null;
    }
    if (base === "loader" && ["bind", "call", "apply"].includes(name)) return "loader-" + name;
    return null;
  }
  function erasedDeclaration(declaration) {
    // declare functions/namespaces, not just variables, are erased. A real
    // implementation merged with an overload/ambient declaration still binds
    // at runtime and must keep its ordinary local shadow semantics.
    for (let node = declaration; node && !ts.isSourceFile(node); node = node.parent)
      if (ts.getCombinedModifierFlags(node) & ts.ModifierFlags.Ambient) return true;
    if (tree.isDeclarationFile || ts.isInterfaceDeclaration(declaration) || ts.isTypeAliasDeclaration(declaration)) return true;
    if (ts.isFunctionDeclaration(declaration)) return !declaration.body;
    return ts.isModuleDeclaration(declaration) && ts.getModuleInstanceState(declaration) === ts.ModuleInstanceState.NonInstantiated;
  }
  function wrapperRedeclaration(declaration) {
    // Every source-file var shares the CJS wrapper binding. Its initializer
    // changes the value only when execution reaches it, including inside an
    // if/block. Function/module/class scopes introduce separate bindings.
    if (!ts.isVariableDeclaration(declaration) ||
      !ts.isVariableDeclarationList(declaration.parent) ||
      (declaration.parent.flags & ts.NodeFlags.BlockScoped)) return false;
    for (let ancestor = declaration.parent; ancestor && !ts.isSourceFile(ancestor); ancestor = ancestor.parent)
      if (ts.isFunctionLike(ancestor) || ts.isModuleDeclaration(ancestor) || ts.isClassLike(ancestor)) return false;
    return true;
  }
  function localReplacement(expression) {
    const value = unwrap(expression);
    if (!value) return false;
    const localFunction = value => ts.isArrowFunction(value) || ts.isFunctionExpression(value);
    return localFunction(value) || (ts.isObjectLiteralExpression(value) && value.properties.every(property =>
      (ts.isPropertyAssignment(property) && !ts.isComputedPropertyName(property.name) &&
        localFunction(unwrap(property.initializer))) ||
      (ts.isMethodDeclaration(property) && !ts.isComputedPropertyName(property.name))));
  }
  function harmless(expression) {
    const node = unwrap(expression);
    if (!node) return true;
    if (ts.isIdentifier(node) || ts.isLiteralExpression(node) ||
        [ts.SyntaxKind.TrueKeyword, ts.SyntaxKind.FalseKeyword, ts.SyntaxKind.NullKeyword].includes(node.kind) ||
        ts.isArrowFunction(node) || ts.isFunctionExpression(node)) return true;
    if (ts.isObjectLiteralExpression(node)) return node.properties.every(property =>
      (ts.isPropertyAssignment(property) && !ts.isComputedPropertyName(property.name) && harmless(property.initializer)) ||
      (ts.isMethodDeclaration(property) && !ts.isComputedPropertyName(property.name)));
    return false;
  }
  // Shallow forward transfer over source-file statements. Facts prove only a
  // definite local function/object replacement. Unknown effects, branches and
  // nested execution discard facts; declaration/assignment order is retained.
  const localsBefore = new Map();
  let locals = new Set();
  function transfer(name, initializer) {
    if (!initializer) return; // var x; does not reset the existing runtime value.
    if (!harmless(initializer)) locals.clear();
    if (ts.isIdentifier(name)) {
      const symbol = checker.getSymbolAtLocation(name);
      if (localReplacement(initializer)) locals.add(symbol);
      else locals.delete(symbol);
    } else locals.clear();
  }
  for (const statement of tree.statements) {
    localsBefore.set(statement, new Set(locals));
    if (ts.isVariableStatement(statement)) {
      for (const declaration of statement.declarationList.declarations) {
        localsBefore.set(declaration, new Set(locals));
        transfer(declaration.name, declaration.initializer);
      }
    } else if (ts.isExpressionStatement(statement)) {
      const expression = unwrap(statement.expression);
      if (ts.isBinaryExpression(expression) && expression.operatorToken.kind === ts.SyntaxKind.EqualsToken &&
          ts.isIdentifier(expression.left)) transfer(expression.left, expression.right);
      else if (!harmless(expression)) locals.clear();
    } else if (!(ts.isEmptyStatement(statement) || ts.isInterfaceDeclaration(statement) ||
                 ts.isTypeAliasDeclaration(statement) || ts.isFunctionDeclaration(statement))) locals.clear();
  }
  function replacedByLocal(node, symbol) {
    // Query only a direct source-file evaluation path, never a closure/branch
    // or an argument whose evaluation could mutate the callee's binding.
    let statement = node;
    while (statement.parent && !ts.isSourceFile(statement.parent)) {
      const parent = statement.parent;
      if (ts.isVariableDeclaration(parent) && parent.initializer === statement)
        return localsBefore.get(parent)?.has(symbol) || false;
      if (!((ts.isPropertyAccessExpression(parent) || ts.isElementAccessExpression(parent) ||
             ts.isCallExpression(parent)) && parent.expression === statement) &&
          !ts.isParenthesizedExpression(parent) && !ts.isAsExpression(parent) &&
          !ts.isTypeAssertionExpression(parent) && !ts.isNonNullExpression(parent) &&
          !ts.isSatisfiesExpression(parent) && !ts.isExpressionStatement(parent)) return false;
      statement = parent;
    }
    return ts.isExpressionStatement(statement) && (localsBefore.get(statement)?.has(symbol) || false);
  }
  function kind(expression, seen = new Set()) {
    const node = unwrap(expression);
    if (!node) return null;
    if (ts.isIdentifier(node)) {
      const symbol = node.parent && ts.isShorthandPropertyAssignment(node.parent) && node.parent.name === node
        ? checker.getShorthandAssignmentValueSymbol(node.parent) : checker.getSymbolAtLocation(node);
      if (!symbol) return node.text === "require" ? "loader" : node.text === "module" ? "commonjs-module" : null;
      if (replacedByLocal(node, symbol)) return null;
      if (seen.has(symbol)) return null;
      const next = new Set(seen); next.add(symbol);
      const declarations = symbol.declarations || [];
      if (declarations.length && declarations.every(declaration =>
        erasedDeclaration(declaration) || (["require", "module"].includes(node.text) && wrapperRedeclaration(declaration))))
        return node.text === "require" ? "loader" : node.text === "module" ? "commonjs-module" : null;
      for (const declaration of declarations) {
        if (ts.isImportSpecifier(declaration)) {
          const statement = declaration.parent.parent.parent;
          if (nodeModules.has(constantString(statement.moduleSpecifier))) {
            const imported = (declaration.propertyName || declaration.name).text;
            if (imported === "createRequire") return "factory";
            if (imported === "Module" || imported === "default") return "module-constructor";
          }
        } else if (ts.isNamespaceImport(declaration) || ts.isImportClause(declaration)) {
          const statement = ts.isImportClause(declaration) ? declaration.parent : declaration.parent.parent;
          if (nodeModules.has(constantString(statement.moduleSpecifier)))
            return ts.isImportClause(declaration) ? "module-constructor" : "module-namespace";
        } else if (ts.isImportEqualsDeclaration(declaration) && ts.isExternalModuleReference(declaration.moduleReference)) {
          if (nodeModules.has(constantString(declaration.moduleReference.expression))) return "module-namespace";
        } else if (ts.isVariableDeclaration(declaration)) {
          const result = kind(declaration.initializer, next);
          if (result) return result;
        } else if (ts.isBindingElement(declaration) && ts.isObjectBindingPattern(declaration.parent)) {
          const variable = declaration.parent.parent;
          if (ts.isVariableDeclaration(variable)) {
            const key = declaration.propertyName || declaration.name;
            const name = ts.isIdentifier(key) ? key.text : ts.isComputedPropertyName(key) ? constantString(key.expression) : constantString(key);
            const result = member(kind(variable.initializer, next), name);
            if (result) return result;
          }
        }
      }
      for (const assigned of assignments.get(symbol) || []) {
        const result = kind(assigned, next);
        if (result) return result;
      }
      return null;
    }
    if (ts.isPropertyAccessExpression(node) || ts.isElementAccessExpression(node))
      return member(kind(node.expression, seen), property(node));
    if (ts.isCallExpression(node)) {
      const called = kind(node.expression, seen);
      if (called === "factory") return "loader";
      if (called === "loader-bind") return node.arguments.length === 1 ? "loader" : "unknown-loader";
      if (called === "loader" && nodeModules.has(constantString(node.arguments[0]))) return "module-namespace";
      if (called === "unknown-loader") return "unknown-loader";
    }
    return null;
  }
  function visit(node) {
    let specifier;
    let loader = false;
    if (ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) specifier = node.moduleSpecifier;
    else if (ts.isImportTypeNode(node) && ts.isLiteralTypeNode(node.argument))
      specifier = node.argument.literal;
    else if (ts.isImportEqualsDeclaration(node) && ts.isExternalModuleReference(node.moduleReference))
      specifier = node.moduleReference.expression;
    else if (ts.isCallExpression(node)) {
      const called = node.expression.kind === ts.SyntaxKind.ImportKeyword ? "loader" : kind(node.expression);
      if (called === "unknown-loader") errors.push("computed module loader cannot be verified statically");
      if (["loader", "loader-call", "loader-apply"].includes(called)) {
        loader = true;
        specifier = called === "loader-call" ? node.arguments[1] : node.arguments[0];
        if (called === "loader-apply") {
          const argumentsArray = unwrap(node.arguments[1]);
          specifier = argumentsArray && ts.isArrayLiteralExpression(argumentsArray) ? argumentsArray.elements[0] : undefined;
        }
      }
    }
    if (specifier || loader) {
      const value = constantString(specifier);
      if (value === null) errors.push("computed module specifier cannot be verified statically");
      else modules.push(value);
    }
    if (ts.isIdentifier(node) || ts.isPropertyAccessExpression(node) ||
      ts.isElementAccessExpression(node) || ts.isCallExpression(node)) {
      const parent = node.parent;
      const reference = kind(node);
      // A locally resolved alias may initialize another binding or be invoked.
      // Passing/returning/wrapping a loader would require arbitrary interprocedural
      // interpretation. Reject that escape instead of silently losing the loader.
      let inType = false;
      for (let ancestor = parent; ancestor && !ts.isStatement(ancestor); ancestor = ancestor.parent)
        if (ts.isTypeNode(ancestor)) { inType = true; break; }
      if (reference && parent && !inType && (parent.name !== node || ts.isShorthandPropertyAssignment(parent))
        && parent.propertyName !== node) {
        const supported = (ts.isCallExpression(parent) && parent.expression === node) ||
          (ts.isVariableDeclaration(parent) && parent.initializer === node) ||
          (ts.isBinaryExpression(parent) && parent.left === node && ts.isIdentifier(node) &&
            [ts.SyntaxKind.EqualsToken, ts.SyntaxKind.BarBarEqualsToken, ts.SyntaxKind.AmpersandAmpersandEqualsToken,
              ts.SyntaxKind.QuestionQuestionEqualsToken].includes(parent.operatorToken.kind)) ||
          (ts.isBinaryExpression(parent) && parent.right === node && ts.isIdentifier(parent.left) &&
            [ts.SyntaxKind.EqualsToken, ts.SyntaxKind.BarBarEqualsToken, ts.SyntaxKind.AmpersandAmpersandEqualsToken,
              ts.SyntaxKind.QuestionQuestionEqualsToken].includes(parent.operatorToken.kind)) ||
          ts.isParenthesizedExpression(parent) || ts.isAsExpression(parent) ||
          ts.isTypeAssertionExpression(parent) || ts.isNonNullExpression(parent) || ts.isSatisfiesExpression(parent) ||
          ts.isExpressionStatement(parent) || ts.isTypeOfExpression(parent) || ts.isVoidExpression(parent) ||
          ((ts.isPropertyAccessExpression(parent) || ts.isElementAccessExpression(parent)) &&
            (["commonjs-module", "module-namespace", "module-constructor"].includes(reference) || kind(parent)));
        if (!supported) errors.push("escaped module loader cannot be verified statically");
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(tree);
  return { path, modules, errors };
});
process.stdout.write(JSON.stringify(results));
