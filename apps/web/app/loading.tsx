import { Spinner } from "@/components/ui";

export default function Loading() {
  return <div className="app-loading"><Spinner label="Carregando produto" /><p>Preparando seu espaço de trabalho.</p></div>;
}
