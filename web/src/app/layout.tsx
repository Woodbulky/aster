import type { Metadata } from "next";
import { DM_Sans, Manrope, Noto_Sans_Devanagari } from "next/font/google";
import "./globals.css";

const dmSans = DM_Sans({ variable: "--font-dm-sans", subsets: ["latin"] });
const manrope = Manrope({ variable: "--font-manrope", subsets: ["latin"] });
const notoDeva = Noto_Sans_Devanagari({
  variable: "--font-noto-deva",
  subsets: ["devanagari"],
});

export const metadata: Metadata = {
  title: "Aster — scholarship forms, one calm step at a time",
  description:
    "Aster helps students prepare scholarship applications by voice or chat in English, Hindi or Marathi.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html
      lang="en"
      className={`${dmSans.variable} ${manrope.variable} ${notoDeva.variable} h-full antialiased`}
    >
      <body className="flex min-h-full flex-col text-base">{children}</body>
    </html>
  );
}
