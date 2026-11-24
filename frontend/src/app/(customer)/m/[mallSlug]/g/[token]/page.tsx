import { GroupView } from "@/components/customer/group-view";

export default async function GroupPage({ params }: PageProps<"/m/[mallSlug]/g/[token]">) {
  const { mallSlug, token } = await params;
  return <GroupView mallSlug={mallSlug} token={token} />;
}
