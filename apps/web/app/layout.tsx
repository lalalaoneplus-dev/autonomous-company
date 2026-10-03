import './globals.css';
import { Sidebar } from '@/components/Sidebar';
import { Header } from '@/components/Header';

export const metadata = {
  title: 'Autonomous Company',
  description: 'Deterministic Autonomous Company Dashboard',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="flex h-screen overflow-hidden bg-background text-foreground antialiased selection:bg-blue-200 selection:text-blue-900 dark:selection:bg-blue-900 dark:selection:text-blue-100">
        <Sidebar />
        <div className="flex-1 md:ml-64 flex flex-col w-full">
          <Header />
          <main className="flex-1 overflow-auto p-4 md:p-6 pb-20">
            {children}
          </main>
        </div>
      </body>
    </html>
  );
}
