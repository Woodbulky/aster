import type { Metadata } from "next";
import { Noto_Sans, Noto_Sans_Devanagari } from "next/font/google";
import "./globals.css";

const notoSans = Noto_Sans({ variable: "--font-noto-sans", subsets: ["latin"] });
const notoDeva = Noto_Sans_Devanagari({
  variable: "--font-noto-deva",
  subsets: ["devanagari"],
});

export const metadata: Metadata = {
  title: "Aster",
  description: "Your voice assistant for scholarship forms — Marathi, Hindi, English.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${notoSans.variable} ${notoDeva.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col text-base">{children}</body>
    </html>
  );
}
