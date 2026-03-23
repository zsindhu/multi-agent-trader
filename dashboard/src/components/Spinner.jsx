export default function Spinner({ size = 'md' }) {
  const px = size === 'sm' ? 'w-4 h-4' : size === 'lg' ? 'w-8 h-8' : 'w-6 h-6'
  return (
    <div className="flex items-center justify-center py-12">
      <div
        className={`${px} border-2 border-[#334155] border-t-blue-500 rounded-full animate-spin`}
      />
    </div>
  )
}
