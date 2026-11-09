export const publicMode =
  document.querySelector('meta[name="tradeguard-public"]')?.getAttribute("content") === "true";
