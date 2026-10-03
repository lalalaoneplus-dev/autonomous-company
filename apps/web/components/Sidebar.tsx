'use client';
import Link from 'next/link';
import { useState } from 'react';
import { usePathname } from 'next/navigation';

export function Sidebar() {
  const [isOpen, setIsOpen] = useState(false);
  const pathname = usePathname();

  const nav = [
    { name: 'Overview', href: '/' },
    { name: 'CEO', href: '/ceo' },
    { name: 'Agents', href: '/agents' },
    { name: 'Opportunities', href: '/opportunities' },
    { name: 'Experiments', href: '/experiments' },
    { name: 'Projects', href: '/projects' },
    { name: 'Treasury', href: '/treasury' },
    { name: 'Transactions', href: '/transactions' },
    { name: 'Approvals', href: '/approvals' },
    { name: 'Memory', href: '/memory' },
    { name: 'Tools', href: '/tools' },
    { name: 'Audit Log', href: '/audit' },
    { name: 'Security', href: '/security' },
    { name: 'Settings', href: '/settings' },
  ];

  return (
    <>
      <button
        className="md:hidden fixed top-4 left-4 z-50 p-2 bg-surface rounded shadow focus-visible:ring-2 focus-visible:ring-blue-500"
        onClick={() => setIsOpen(!isOpen)}
        aria-label="Toggle Menu"
        aria-expanded={isOpen}
      >
        {isOpen ? '×' : '☰'}
      </button>
      <aside className={`fixed inset-y-0 left-0 transform ${isOpen ? 'translate-x-0' : '-translate-x-full'} md:translate-x-0 transition-transform duration-200 ease-in-out w-64 bg-surface border-r border-border flex flex-col h-screen z-40`}>
        <div className="p-4 pl-16 md:pl-4 border-b border-border font-bold text-lg flex items-center justify-between">
          <span>Autonomous Co</span>
        </div>
        <nav className="flex-1 overflow-y-auto p-3 space-y-1">
          {nav.map((item) => {
            const active = pathname === item.href;
            return (
              <Link
                key={item.name}
                href={item.href}
                onClick={() => setIsOpen(false)}
                className={`block px-3 py-2 rounded-md transition-colors text-sm font-medium focus-visible:ring-2 focus-visible:ring-blue-500 ${active ? 'bg-blue-600/10 text-blue-600 dark:text-blue-400' : 'hover:bg-border text-gray-700 dark:text-gray-300'}`}
              >
                {item.name}
              </Link>
            );
          })}
        </nav>
      </aside>
    </>
  );
}
