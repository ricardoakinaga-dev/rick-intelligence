"use client";

export default function ErrorPage({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  return (
    <div className="page">
      <div className="state-box">
        <h3>Algo falhou na interface</h3>
        <p>{error.message}</p>
        <button type="button" className="ui-button primary" onClick={reset}>
          Recarregar
        </button>
      </div>
    </div>
  );
}
