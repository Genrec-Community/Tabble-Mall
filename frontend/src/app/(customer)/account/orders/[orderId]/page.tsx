import { OrderView } from "@/components/customer/order-view";

export default async function OrderPage({ params }: PageProps<"/account/orders/[orderId]">) {
  const { orderId } = await params;
  return <OrderView orderId={orderId} />;
}
