export const formatWhen = (iso: string) =>
  new Date(iso).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export const formatMoney = (amount: string | number, currency = "USD") =>
  new Intl.NumberFormat(undefined, { style: "currency", currency }).format(Number(amount));

// "YYYY-MM-DD" shown as a calendar day. Parsed as local time so the day never shifts with the timezone.
export const formatDay = (ymd: string) => {
  const [y, m, d] = ymd.split("-").map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
};

// Today as "YYYY-MM-DD" in the viewer's local time (for <input type="date" min>).
export const todayLocal = () => {
  const d = new Date();
  d.setMinutes(d.getMinutes() - d.getTimezoneOffset());
  return d.toISOString().slice(0, 10);
};
