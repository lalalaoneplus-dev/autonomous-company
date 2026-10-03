export function ErrorAlert({ message }: { message: string }) {
  if (!message) return null;
  return (
    <div className="p-4 mb-4 text-sm text-red-800 rounded-lg bg-red-50 dark:bg-gray-800 dark:text-red-400 border border-red-300 dark:border-red-800" role="alert">
      <span className="font-medium">Error:</span> {message}
    </div>
  );
}
