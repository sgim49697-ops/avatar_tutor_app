// layout.tsx - root layout for the avatar tutor POC frontend
import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Avatar Tutor POC",
  description: "Real-time AI coach avatar proof of concept",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}

