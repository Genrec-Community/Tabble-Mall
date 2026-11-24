/** Cuisine labels for the store food types (server- and client-safe). */
export const FOOD_TYPE_LABELS: Record<string, string> = {
  fast_food: "Fast food",
  meals: "Meals",
  snacks: "Snacks",
  beverages: "Beverages",
  desserts: "Desserts",
  bakery: "Bakery",
  healthy: "Healthy",
  chinese: "Chinese",
  south_indian: "South Indian",
  north_indian: "North Indian",
};

export function cuisines(types: string[]): string {
  return types.map((t) => FOOD_TYPE_LABELS[t] ?? t).join(" · ");
}
