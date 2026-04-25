function Navbar() {
  return (
    <nav className="w-full bg-white border-b border-gray-200 px-6 py-4">
      <div className="flex items-center justify-between max-w-7xl mx-auto">
        
        {/* 左边:Logo/站名 */}
        <div className="text-2xl font-bold text-orange-600">
          🎓 RateMyClass @ Oxy
        </div>

        {/* 右边:导航链接 + 登录按钮 */}
        <div className="flex items-center gap-6">
          <a href="/" className="text-gray-700 hover:text-orange-600">
            Home
          </a>
          <a href="/browse" className="text-gray-700 hover:text-orange-600">
            Browse
          </a>
          <a className="bg-orange-600 text-white px-4 py-2 rounded-full hover:bg-orange-700">
            Sign In
          </a>
        </div>

      </div>
    </nav>
  )
}

export default Navbar