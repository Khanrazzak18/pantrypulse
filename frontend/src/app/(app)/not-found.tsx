import Link from "next/link";

export default function NotFound() {
  return (
    <div className="rounded-lg border border-stone-200 bg-white p-6">
      <h1 className="text-xl font-semibold">We couldn&apos;t find that</h1>
      <p className="mt-1 text-stone-600">It may have been removed, or the link is wrong.</p>
      <Link href="/" className="mt-3 inline-block font-medium text-green-800 hover:underline">
        Go to your home page
      </Link>
    </div>
  );
}
