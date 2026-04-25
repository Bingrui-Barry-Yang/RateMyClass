// 定义课程的数据结构(TypeScript 类型)
export type Course = {
  id: number
  code: string         // 课程代号,如 "CS 101"
  name: string         // 课程名,如 "Intro to Computer Science"
  professor: string    // 授课教授
  rating: number       // 平均评分 0-5
  reviewCount: number  // 评价数量
  department: string   // 系/学科
}

// 假数据:6 门课
export const mockCourses: Course[] = [
  {
    id: 1,
    code: "CS 101",
    name: "Intro to Computer Science",
    professor: "Prof. Smith",
    rating: 4.8,
    reviewCount: 124,
    department: "Computer Science"
  },
  {
    id: 2,
    code: "MATH 110",
    name: "Calculus I",
    professor: "Prof. Johnson",
    rating: 4.7,
    reviewCount: 98,
    department: "Mathematics"
  },
  {
    id: 3,
    code: "ENGL 220",
    name: "American Literature",
    professor: "Prof. Lee",
    rating: 4.6,
    reviewCount: 87,
    department: "English"
  },
  {
    id: 4,
    code: "PSYC 101",
    name: "Introduction to Psychology",
    professor: "Prof. Garcia",
    rating: 4.5,
    reviewCount: 156,
    department: "Psychology"
  },
  {
    id: 5,
    code: "BIO 130",
    name: "General Biology",
    professor: "Prof. Chen",
    rating: 4.4,
    reviewCount: 73,
    department: "Biology"
  },
  {
    id: 6,
    code: "ECON 101",
    name: "Principles of Economics",
    professor: "Prof. Williams",
    rating: 4.3,
    reviewCount: 109,
    department: "Economics"
  }
]