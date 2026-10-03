export function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center p-12 text-center border-2 border-dashed border-border rounded-lg bg-surface text-gray-500">
      <p>{message}</p>
    </div>
  );
}
