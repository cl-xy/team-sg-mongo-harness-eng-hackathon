import type { Metadata } from "next";
import "./globals.css";
export const metadata: Metadata = {
  title: "Long Horizon · Memory intelligence",
  description:
    "Follow every step from NYC 311 complaints to persistent memory and evidence-supported recommendations.",
};
export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
