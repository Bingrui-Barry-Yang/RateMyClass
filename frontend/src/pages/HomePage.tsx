import Navbar from '../components/Navbar'
import CourseCard from '../components/CourseCard'
import { mockCourses } from '../data/mockCourses'

function HomePage() {
  return (
    <div className="min-h-screen bg-white">
      <Navbar />
      
      {/* Hero Section */}
      <section className="bg-gradient-to-b from-white to-orange-50 py-20 px-6">
        {/* 标题+简介 */}
        <div className="max-w-4xl mx-auto text-center">
          <h1 className="text-5xl font-bold text-gray-900 mb-6">
            Find Your Next Great Class
          </h1>
          <p className="text-xl text-gray-600 mb-10">
            Read real reviews from Oxy students about courses and professors before you enroll.
          </p>
          {/* 搜索栏 */}
          <div className="flex gap-3 max-w-2xl mx-auto">
            <input
              type="text"
              placeholder="Search courses or professors..."
              className="flex-1 px-5 py-3 rounded-lg border border-gray-300 focus:outline-none focus:border-orange-600"
            />
            <button className="bg-orange-600 text-white px-6 py-3 rounded-lg font-semibold hover:bg-orange-700">
              Search
            </button>
          </div>
        </div>
      </section>

      {/* Top Rated Courses Section */}
      <section className="py-20 px-6">
        <div className="max-w-6xl mx-auto">
          
          {/* 区块标题 */}
          <div className="text-center mb-12">
            <h2 className="text-4xl font-bold text-gray-900 mb-3">
              Top Rated Courses
            </h2>
            <p className="text-lg text-gray-600">
              Highest rated classes by Oxy students
            </p>
          </div>

          {/* 课程卡片网格 */}
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
            {mockCourses.map(course => (
              <CourseCard key={course.id} course={course} />
            ))}
          </div>

        </div>
      </section>
      
    </div>
  )
}

export default HomePage