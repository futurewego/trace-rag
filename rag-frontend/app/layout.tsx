import "./globals.css";
import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "知识库问答 Demo",
  description: "上传 PDF，提问，获取带页码引用的答案",
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
          <h1>📚 知识库问答 Demo</h1>
          <nav>
            <Link href="/">问答</Link>
            <Link href="/documents">文档</Link>
          </nav>
        </header>
        <main>{children}</main>
      </body>
    </html>
  );
}
