export default function Loading() {
  return (
    <div className="page stack">
      <div className="state-box">
        <h3>Carregando interface</h3>
        <p>Montando shell, dados e navegação.</p>
      </div>
      <div className="skeleton" style={{ minHeight: 180 }} />
    </div>
  );
}
