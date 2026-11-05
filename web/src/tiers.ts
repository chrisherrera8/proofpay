export interface Tier {
  id: "basic" | "deep" | "deluxe";
  name: string;
  price: number;
  blurb: string;
  features: string[];
  popular?: boolean;
}

// `id` is the backend service_type. Prices must match what the API accepts for that job.
export const TIERS: Tier[] = [
  {
    id: "basic",
    name: "Basic Clean",
    price: 10,
    blurb: "A quick refresh of the essentials.",
    features: ["Kitchen", "Bathroom", "Floors", "Surfaces"],
  },
  {
    id: "deep",
    name: "Deep Clean",
    price: 20,
    blurb: "Everything in Basic, plus the places that get skipped.",
    features: ["Everything in Basic", "Oven", "Baseboards", "Inside cabinets"],
    popular: true,
  },
  {
    id: "deluxe",
    name: "Deluxe Clean",
    price: 30,
    blurb: "The full treatment, top to bottom.",
    features: ["Everything in Deep", "Inside refrigerator", "Windows", "Laundry folded"],
  },
];

export const tierById = (id: string | null) => TIERS.find((t) => t.id === id);
