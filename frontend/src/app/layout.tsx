import type { Metadata, Viewport } from "next";
import { Geist, Geist_Mono, Montserrat } from "next/font/google";
import "./globals.css";
import { Providers } from "./providers";

const geistSans = Geist({
  variable: "--font-geist-sans",
  subsets: ["latin"],
});

// The customer pages' display face (after Tabble's diner screens). Not preloaded: staff pages never use it.
const montserrat = Montserrat({
  variable: "--font-montserrat",
  subsets: ["latin"],
  preload: false,
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: "MallT",
  description: "Order from every store in the mall with one QR.",
  icons: { apple: "/icons/apple-touch-icon.png" },
  appleWebApp: { capable: true, title: "MallT", statusBarStyle: "black" },
};

export const viewport: Viewport = { themeColor: "#000000" };

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${geistSans.variable} ${geistMono.variable} ${montserrat.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col"><Providers>{children}</Providers></body>
    </html>
  );
}
