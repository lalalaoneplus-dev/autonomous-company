export function Loading() {
  return <div className="flex items-center justify-center p-8 space-x-2">
    <div className="w-4 h-4 rounded-full bg-blue-600 animate-bounce" />
    <div className="w-4 h-4 rounded-full bg-blue-600 animate-bounce" style={{ animationDelay: '0.1s' }} />
    <div className="w-4 h-4 rounded-full bg-blue-600 animate-bounce" style={{ animationDelay: '0.2s' }} />
  </div>;
}
