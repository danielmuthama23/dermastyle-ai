import "./globals.css";

export const metadata = {
  title: "DermaStyle AI",
  description: "One shopping plan for your skin and your style, built on YouCam Skin AI and Apparel Virtual Try-On.",
};
export const viewport = { width: "device-width", initialScale: 1 };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
