export const formatWhen = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export const formatMoney = (amount: string | number, currency = "USD") =>
  new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(amount));
