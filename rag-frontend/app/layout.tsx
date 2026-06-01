import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "RAG MVP",
  description: "Enterprise RAG — M1",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="zh-CN">
      <body>
        <header>
          <h1>RAG MVP</h1>
          <nav>
            <Link href="/">Chat</Link>
            <Link href="/documents">Documents</Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
