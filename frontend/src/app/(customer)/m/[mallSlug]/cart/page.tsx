import { CartView } from "@/components/customer/cart-view";

export default async function CartPage({ params }: PageProps<"/m/[mallSlug]/cart">) {
  const { mallSlug } = await params;
  return <CartView mallSlug={mallSlug} />;
}
