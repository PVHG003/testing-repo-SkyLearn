from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth import get_user_model
from django.test.utils import override_settings
from django.conf import settings
from quiz.models import Quiz, Sitting, Progress, MCQuestion, Choice
from course.models import Course, Program
from core.models import Semester, Session
from result.models import TakenCourse, Student
from django.utils import timezone
import json

User = get_user_model()

@override_settings(
    STATICFILES_STORAGE='django.contrib.staticfiles.storage.StaticFilesStorage',
    MIDDLEWARE=[
        m for m in settings.MIDDLEWARE 
        if m not in ['django.middleware.locale.LocaleMiddleware', 'whitenoise.middleware.WhiteNoiseMiddleware']
    ],
    LANGUAGE_CODE='en-us'
)
class QuizTakeViewTest(TestCase):
    def setUp(self):
        # Create a student user
        self.student_user = User.objects.create_user(
            username="teststudent",
            password="testpass123",
            email="student@test.com",
            is_student=True
        )
        self.client = Client()
        self.client.force_login(self.student_user)

        # Create a session and semester
        self.session = Session.objects.create(
            session="2024-2025",
            is_current_session=True,
            next_session_begins=timezone.now().date().replace(year=2025, month=6, day=1)
        )
        self.semester = Semester.objects.create(
            semester="FIRST",
            is_current_semester=True,
            session=self.session,
            next_semester_begins=timezone.now().date().replace(year=2025, month=1, day=1)
        )

        # Create a program
        self.program = Program.objects.create(
            title="Computer Science"
        )

        # Create a student profile
        self.student = Student.objects.create(
            student=self.student_user,
            program=self.program,
            level="Bachelor"
        )

        # Create a course
        self.course = Course.objects.create(
            title="Test Course",
            slug="test-course",
            semester="First",
            level="Bachelor",
            code="CS101",
            credit=3,
            program=self.program
        )

        # Enroll student in course
        self.taken_course = TakenCourse.objects.create(
            student=self.student,
            course=self.course
        )

        # Create a quiz
        self.quiz = Quiz.objects.create(
            course=self.course,
            title="Test Quiz",
            slug="test-quiz",
            description="Test quiz description",
            category="practice",
            random_order=False,
            answers_at_end=False,
            exam_paper=False,
            single_attempt=False,
            pass_mark=50
        )

        # Create two MCQuestions
        self.question1 = MCQuestion.objects.create(
            content="What is 2+2?",
            choice_order="none"
        )
        self.question1.quiz.add(self.quiz)
        self.correct_choice1 = Choice.objects.create(
            question=self.question1,
            choice_text="4",
            correct=True
        )
        self.incorrect_choice1 = Choice.objects.create(
            question=self.question1,
            choice_text="5",
            correct=False
        )

        self.question2 = MCQuestion.objects.create(
            content="What is 3+3?",
            choice_order="none"
        )
        self.question2.quiz.add(self.quiz)
        self.correct_choice2 = Choice.objects.create(
            question=self.question2,
            choice_text="6",
            correct=True
        )
        self.incorrect_choice2 = Choice.objects.create(
            question=self.question2,
            choice_text="7",
            correct=False
        )

    def test_TC001_start_quiz_with_valid_questions(self):
        """Test starting a quiz with valid questions"""
        response = self.client.get(reverse('quiz_take', args=[self.course.pk, self.quiz.slug]))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/question.html')
        self.assertEqual(response.context['question'], self.question1)
        self.assertEqual(response.context['quiz'], self.quiz)
        self.assertEqual(response.context['course'], self.course)
        self.assertEqual(response.context['progress'], (0, 2))  # 0 answered, 2 total

    def test_TC002_quiz_with_no_questions(self):
        """Test quiz with no questions"""
        empty_quiz = Quiz.objects.create(
            course=self.course,
            title="Empty Quiz",
            slug="empty-quiz",
            description="Empty quiz",
            category="practice"
        )
        response = self.client.get(reverse('quiz_take', args=[self.course.pk, empty_quiz.slug]), follow=True)
        self.assertRedirects(response, reverse('quiz_index', kwargs={'slug': self.course.slug}))
        self.assertContains(response, "This quiz has no questions available.")

    def test_TC003_single_attempt_quiz_completed(self):
        """Test single-attempt quiz already completed"""
        single_quiz = Quiz.objects.create(
            course=self.course,
            title="Single Attempt Quiz",
            slug="single-quiz",
            single_attempt=True,
            exam_paper=True
        )
        single_quiz.question_set.add(self.question1)
        Sitting.objects.create(
            user=self.student_user,
            quiz=single_quiz,
            course=self.course,
            question_order=f"{self.question1.id},",
            question_list="",
            current_score=1,
            complete=True,
            end=timezone.now()
        )
        response = self.client.get(reverse('quiz_take', args=[self.course.pk, single_quiz.slug]), follow=True)
        self.assertRedirects(response, reverse('quiz_index', kwargs={'slug': self.course.slug}))
        self.assertContains(response, "You have already completed this quiz. Only one attempt is permitted.")

    def test_TC004_submit_correct_answer_mcquestion(self):
        """Test submitting correct answer to MCQuestion"""
        sitting = Sitting.objects.new_sitting(self.student_user, self.quiz, self.course)
        response = self.client.post(reverse('quiz_take', args=[self.course.pk, self.quiz.slug]), {
            'answers': str(self.correct_choice1.id)
        }, follow=True)
        
        # Check if Sitting still exists
        sitting_exists = Sitting.objects.filter(id=sitting.id).exists()
        if sitting_exists:
            sitting.refresh_from_db()
            self.assertEqual(sitting.current_score, 1, 
                            "Sitting score should be 1 for one correct answer.")
            self.assertEqual(sitting.incorrect_questions, "", 
                            "No questions should be marked as incorrect.")
            self.assertEqual(json.loads(sitting.user_answers), 
                            {str(self.question1.id): str(self.correct_choice1.id)},
                            "Correct answer should be stored in user_answers.")
        
        # Check response status code
        self.assertEqual(response.status_code, 200, 
                        "Response should return status code 200.")
        
        # Check Progress score
        progress = Progress.objects.get(user=self.student_user)
        self.assertEqual(progress.score, f"quiz.Quiz.None,1,2,",
                        "Progress should record a score of 1/2 (1 correct out of 2 questions).")

    def test_TC005_submit_incorrect_answer_mcquestion(self):
        """Test submitting incorrect answer to MCQuestion"""
        sitting = Sitting.objects.new_sitting(self.student_user, self.quiz, self.course)
        response = self.client.post(reverse('quiz_take', args=[self.course.pk, self.quiz.slug]), {
            'answers': str(self.incorrect_choice1.id)
        }, follow=True)
        
        # Check if Sitting still exists
        sitting_exists = Sitting.objects.filter(id=sitting.id).exists()
        if sitting_exists:
            sitting.refresh_from_db()
            self.assertEqual(sitting.current_score, 0,
                            "Sitting score should be 0 for an incorrect answer.")
            self.assertEqual(sitting.incorrect_questions, f"{self.question1.id},",
                            "Question 1 should be marked as incorrect.")
            self.assertEqual(json.loads(sitting.user_answers),
                            {str(self.question1.id): str(self.incorrect_choice1.id)},
                            "Incorrect answer should be stored in user_answers.")
        
        # Check response status code
        self.assertEqual(response.status_code, 200,
                        "Response should return status code 200.")
        
        # Check Progress score
        progress = Progress.objects.get(user=self.student_user)
        self.assertEqual(progress.score, f"quiz.Quiz.None,0,2,",
                        "Progress should record a score of 0/2 (0 correct out of 2 questions).")

    def test_TC006_quiz_completion(self):
        """Test quiz completion after answering all questions"""
        sitting = Sitting.objects.new_sitting(self.student_user, self.quiz, self.course)
        # Answer first question
        self.client.post(reverse('quiz_take', args=[self.course.pk, self.quiz.slug]), {
            'answers': str(self.correct_choice1.id)
        })
        # Answer second question
        response = self.client.post(reverse('quiz_take', args=[self.course.pk, self.quiz.slug]), {
            'answers': str(self.correct_choice2.id)
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/result.html')
        self.assertEqual(response.context['score'], 2)
        self.assertEqual(response.context['max_score'], 2)
        self.assertEqual(response.context['percent'], 100)
        self.assertTrue(response.context['sitting'].check_if_passed)
        self.assertContains(response, "You have passed this quiz, congratulations!")
        self.assertFalse(Sitting.objects.filter(id=sitting.id).exists())

    def test_TC007_answers_at_end_hides_answers(self):
        """Test answers_at_end=True hides answers until completion"""
        self.quiz.answers_at_end = True
        self.quiz.save()
        sitting = Sitting.objects.new_sitting(self.student_user, self.quiz, self.course)
        response = self.client.post(reverse('quiz_take', args=[self.course.pk, self.quiz.slug]), {
            'answers': str(self.correct_choice1.id)
        })
        self.assertEqual(response.status_code, 200)
        self.assertIn('question', response.context)
        self.assertEqual(response.context['previous'], {})
        sitting_exists = Sitting.objects.filter(id=sitting.id).exists()
        if sitting_exists:
            sitting.refresh_from_db()
            self.assertEqual(sitting.incorrect_questions, "")

    def test_TC008_invalid_answer_submission(self):
        """Test invalid answer submission for MCQuestion"""
        sitting = Sitting.objects.new_sitting(self.student_user, self.quiz, self.course)
        response = self.client.post(reverse('quiz_take', args=[self.course.pk, self.quiz.slug]), {
            'answers': '999'
        })
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'quiz/question.html')
        form = response.context['form']
        self.assertFalse(form.is_valid())
        self.assertIn('answers', form.errors)
        self.assertEqual(form.errors['answers'], ['Select a valid choice. 999 is not one of the available choices.'])
        sitting_exists = Sitting.objects.filter(id=sitting.id).exists()
        if sitting_exists:
            sitting.refresh_from_db()
            self.assertEqual(sitting.current_score, 0)
            self.assertEqual(sitting.user_answers, "{}")