// Aplica a preferência antes do CSS e da primeira consulta autenticada.
try {
  document.documentElement.dataset.tema =
    localStorage.getItem("nexoflow.central.tema") === "grafite"
      ? "grafite"
      : "claro";
} catch {
  document.documentElement.dataset.tema = "claro";
}
