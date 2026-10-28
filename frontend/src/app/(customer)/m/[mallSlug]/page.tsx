export default async function MallPage({ params }: PageProps<"/m/[mallSlug]">) {
  const { mallSlug } = await params;
  return <main className="p-6">Mall: {mallSlug}</main>;
}
