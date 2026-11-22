import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "Resume Studio",
    template: "%s — Resume Studio",
  },
  description:
    "Local-first AI resume builder: parse your master resume, edit it, export a pixel-perfect PDF.",
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
