import type { ReactNode } from "react";

// Use in a test file (vi.mock is only hoisted there):
//   vi.mock("@paypal/react-paypal-js", async () => (await import("@/test/paypal-stub")).paypalModule);
// then drive the buttons through `paypal.props`, e.g. `await paypal.props.createOrder()`.

/* eslint-disable @typescript-eslint/no-explicit-any */
export const paypal: { props: any } = { props: null };

function PayPalButtons(props: any) {
  // 8.9.2 hands the latest props to the real buttons, so the latest props are the faithful thing to keep.
  paypal.props = props;
  return <button type="button">PayPal</button>;
}

function PayPalScriptProvider({ children }: { children: ReactNode }) {
  return <>{children}</>;
}

export const paypalModule = { PayPalScriptProvider, PayPalButtons };
