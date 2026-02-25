export function LoadingSpinner({ className = "h-8 w-8" }: { className?: string }) {
  return (
    <div className="flex items-center justify-center p-8">
      <div
        className={`animate-spin rounded-full border-2 border-primary-500 border-t-transparent ${className}`}
      />
    </div>
  );
}
