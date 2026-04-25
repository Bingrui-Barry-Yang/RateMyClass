import type { Course } from '../data/mockCourses'

// 定义这个组件接受的 props(参数)
type CourseCardProps = {
  course: Course
}

function CourseCard({ course }: CourseCardProps) {
  return (
    <div className="bg-white border border-gray-200 rounded-xl p-6 hover:shadow-lg hover:border-orange-300 transition cursor-pointer">
      
      {/* 顶部:课程编号 + 系名 */}
      <div className="flex items-center justify-between mb-3">
        <span className="text-sm font-semibold text-orange-600">
          {course.code}
        </span>
        <span className="text-xs text-gray-500">
          {course.department}
        </span>
      </div>

      {/* 课程名 */}
      <h3 className="text-lg font-bold text-gray-900 mb-2">
        {course.name}
      </h3>

      {/* 教授 */}
      <p className="text-sm text-gray-600 mb-4">
        {course.professor}
      </p>

      {/* 底部:评分 + 评价数 */}
      <div className="flex items-center gap-2">
        <span className="text-yellow-500">⭐</span>
        <span className="font-bold text-gray-900">{course.rating}</span>
        <span className="text-sm text-gray-500">
          ({course.reviewCount} reviews)
        </span>
      </div>

    </div>
  )
}

export default CourseCard