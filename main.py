import base64
import io
import json
from datetime import datetime
from typing import List

import aiohttp
from aiogram import Bot, Dispatcher, executor, types
from aiogram.dispatcher.filters.state import StatesGroup, State
from aiogram.types import InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup
from aiogram.dispatcher import FSMContext
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.contrib.middlewares.logging import LoggingMiddleware

from test_example import test_example

bot = Bot(token="1308187367:AAEtB3yFALotsg9RwLBBkGfVv2MRl2a1yWw")

dp = Dispatcher(bot, storage=MemoryStorage())
dp.middleware.setup(LoggingMiddleware())

resume_analyzer_api = "https://lod-resume-analyze.herokuapp.com"
get_vacancies_route = "/get-relevant-vacancies"

vacancies_api = "https://employee-recruiting-api.herokuapp.com"
headers_json = {'Content-Type': 'application/json'}


def build_vacancies_buttons(vacancies):
    kb_full = InlineKeyboardMarkup(row_width=1)
    keys_list = (
        KeyboardButton(vacancy['title'], url=vacancy['url']) for vacancy in vacancies
    )
    kb_full.add(*keys_list)
    return kb_full


def build_vacancies_keyboard(vacancies):
    kb_full = ReplyKeyboardMarkup(row_width=1, one_time_keyboard=True)
    keys_list = (
        KeyboardButton(vacancy['title']) for vacancy in vacancies
    )
    kb_full.add(*keys_list)
    return kb_full


def build_readiness_buttons():
    kb = ReplyKeyboardMarkup(one_time_keyboard=True)
    kb.add(KeyboardButton("Начать тестирование✍️"))
    return kb


def build_answers_buttons(answers: List[str]):
    kb = ReplyKeyboardMarkup(one_time_keyboard=True, row_width=2)
    keys_list = (
        KeyboardButton(answer)
        for answer in answers
    )
    kb.add(*keys_list)
    return kb


class CandidateScreening(StatesGroup):
    waiting_for_creds = State()
    waiting_for_resume = State()
    waiting_for_test_choose = State()
    waiting_for_readiness = State()
    waiting_for_answers = State()


async def async_request_json(url, method, data=None, params=None, headers=None):
    async with aiohttp.request(method=method, url=url, params=params, data=data, headers=headers) as response:
        result = await response.json()
    return result


async def async_request_bytes(url, method, data=None, params=None, headers=None):
    async with aiohttp.request(method=method, url=url, params=params, data=data, headers=headers) as response:
        result = response
    return result


async def send_answers(state: FSMContext):
    state_data = await state.get_data()
    screening_test_id = state_data.get('screening_test_id')
    vacancy_id = state_data.get('vacancy_id')
    candidate_id = state_data.get('candidate_id')
    candidate_answers = state_data.get('candidate_answers')
    start_date = state_data.get('start_date')
    end_date = state_data.get('end_date')

    path = f"api/vacancies/{vacancy_id}/candidates/{candidate_id}/screening-tests/{screening_test_id}/results"
    url = f"{vacancies_api}/{path}"
    data = dict(
        candidateAnswers=candidate_answers,
        startDate=start_date.isoformat(),
        endDate=end_date.isoformat(),
    )

    result = await async_request_bytes(url, "POST", data=json.dumps(data), headers=headers_json)
    return result


async def load_screening(vacancy_id):
    tests_path = f'api/vacancies/{vacancy_id}/screening-tests'
    tests_url = f"{vacancies_api}/{tests_path}"
    screening_tests = (await async_request_json(tests_url, 'GET'))['data']
    if len(screening_tests) == 0:
        return test_example['questions']

    test_for_candidate = screening_tests[-1]

    questions_path = f"api/vacancies/{vacancy_id}/screening-tests/{test_for_candidate['id']}/questions"
    questions_url = f'{vacancies_api}/{questions_path}'
    questions = (await async_request_json(questions_url, 'GET'))['data']
    return test_for_candidate['id'], questions


async def create_candidate(state: FSMContext):
    state_data = await state.get_data()
    creds = state_data.get('creds')
    name = creds.get('name').split(' ')
    candidate = dict(
        firstName=name[0] if len(name) > 0 else '',
        surName=name[1] if len(name) > 1 else '',
        patrName=name[2] if len(name) > 2 else '',
        telegram=creds.get('telegram'),
        resume=state_data.get('resume')
    )
    vacancy_id = state_data['vacancy_id']
    path = f"api/vacancies/{vacancy_id}/candidates"
    url = f"{vacancies_api}/{path}"
    result = await async_request_json(url, 'POST', data=json.dumps(candidate), headers=headers_json)
    return result


async def process_resume(resume_file, message, state, filename='textfile', fileextension='txt'):
    try:
        resume_copy = io.BytesIO(resume_file.getvalue())
        await state.update_data(
            resume=dict(
                data=str(base64.b64encode(resume_copy.getvalue())),
                fileName=filename,
                fileExtension=fileextension
            )
        )

        url = f"{resume_analyzer_api}{get_vacancies_route}"
        vacancies = await async_request_json(url, "POST", data={'resume': resume_file})
        vacancies = vacancies['vacancies']
    except Exception as e:
        print(str(e))
        await message.reply("❗️Произошла какая-то ошибка с анализатором😢 Мы уже решаем эту проблему!🛠 Попробуйте "
                            "позже🤓")
        return

    buttons = build_vacancies_buttons(vacancies)
    await message.reply(f"А вот и твои вакансии подъехали!📨 "
                        f"Выбери вакансию, на которую хотел бы пройти тестирование📚",
                        reply_markup=buttons)
    keyboard = build_vacancies_keyboard(vacancies)
    await message.answer(text='После того, как выберешь вакансию, '
                              'нажми на одну из кнопок чтобы начать тестирование.✍️',
                         reply_markup=keyboard)
    await state.update_data(available_vacancies=[
        dict(
            title=vacancy['title'],
            url=vacancy['url'],
            id=vacancy['id']
        ) for vacancy in vacancies]
    )
    await CandidateScreening.waiting_for_test_choose.set()


@dp.message_handler(commands=["start"], state="*")
async def creds(message: types.Message):
    await message.answer("Привет!👋 Это бот для поиска вакансий. Напиши нам своё Ф.И.О📝")
    await CandidateScreening.waiting_for_creds.set()


@dp.message_handler(state=CandidateScreening.waiting_for_creds)
async def vacancies(message: types.Message, state: FSMContext):
    if len(message.text) < 1:
        await message.answer("Введите своё ФИО 🤓")
        return
    await state.update_data(creds=dict(name=message.text, telegram=message.from_user.url))
    await message.answer("Отлично!👍 Сбрось своё резюме, и мы попробуем показать тебе наиболее релевантные вакансии!😉")
    await CandidateScreening.waiting_for_resume.set()
    return


@dp.message_handler(content_types=types.ContentTypes.DOCUMENT, state=CandidateScreening.waiting_for_resume)
async def resume_doc(message: types.Message, state: FSMContext):
    try:
        document = message.document
        file_id = document.file_id
        resume = await bot.get_file(file_id)
        file_path = resume.file_path
        resume_file: io.BytesIO = await bot.download_file(file_path)
    except Exception as e:
        print(str(e))
        await message.reply("Кажется, что-то не так с файлом 🤯 Попробуй скинуть в формате txt!📄")
        return

    file = document.file_name.split('.')
    filename = file[0]
    fileextension = file[1] if len(file) > 1 else 'txt'

    await message.reply("Файл принят!👍 Подожди немного⏳")
    await process_resume(resume_file, message, state, filename=filename, fileextension=fileextension)


@dp.message_handler(content_types=types.ContentTypes.TEXT, state=CandidateScreening.waiting_for_resume)
async def resume_text(message: types.Message, state: FSMContext):
    resume_file = io.BytesIO(message.text.encode())
    await message.reply("Резюме принято! ✅ Подожди немного⏳")
    await process_resume(resume_file, message, state)


@dp.message_handler(state=CandidateScreening.waiting_for_test_choose, content_types=types.ContentTypes.TEXT)
async def choose_test(message: types.Message, state: FSMContext):
    chosen_vacancy_name = message.text
    sm_data = await state.get_data()
    available_vacancies = sm_data['available_vacancies']
    test_names = [test['title'] for test in available_vacancies]
    if chosen_vacancy_name not in test_names:
        await message.reply('❗️Кажется, ты написал что-то не то😢 Нажми на одну из кнопок на клавиатуре.☝️')
        return

    chosen_vacancy = list(filter(lambda x: x['title'] == chosen_vacancy_name, available_vacancies))[0]

    test_id, questions = await load_screening(chosen_vacancy['id'])
    await state.update_data(test=questions, vacancy_id=chosen_vacancy['id'], screening_test_id=test_id)
    readiness_keyboard = build_readiness_buttons()
    await message.reply('Отличный выбор!👍 Нажми "Начать тестирование" когда будешь готов сдавать тест!✔️ \n'
                        '❗️Имей ввиду, что время прохождения тестирования тоже будет учитываться.⏳',
                        reply_markup=readiness_keyboard)
    await CandidateScreening.waiting_for_readiness.set()


@dp.message_handler(state=CandidateScreening.waiting_for_readiness, content_types=types.ContentTypes.TEXT)
async def start_test(message: types.Message, state: FSMContext):
    answer = message.text
    if answer != "Начать тестирование✍️":
        return

    await message.answer('Окей, начинаем!😉')
    await CandidateScreening.waiting_for_answers.set()
    await state.update_data(
        data=dict(
            current_question=0,
            start_date=datetime.now(),
            candidate_answers=[]
        )
    )
    data = await state.get_data()
    questions = data['test']
    first_question = questions[0]['text']
    answers_keys = build_answers_buttons([answer['text'] for answer in questions[0]['answers']])
    await message.answer(first_question, reply_markup=answers_keys)


@dp.message_handler(state=CandidateScreening.waiting_for_answers, content_types=types.ContentTypes.TEXT)
async def answer_question(message: types.Message, state: FSMContext):
    answer = message.text
    state_data = await state.get_data()
    current_question_number = state_data['current_question']
    available_answers = state_data['test'][current_question_number]['answers']

    if answer not in [text['text'] for text in available_answers]:
        await message.reply('Выбери один из ответов с клавиатуры 📲')
        return

    candidate_answer = list(filter(lambda x: x['text'] == answer, available_answers))[0]
    question = state_data['test'][current_question_number]
    candidate_answers = state_data.get('candidate_answers')
    candidate_answers.append(dict(questionId=question['id'], answerId=candidate_answer['id']))
    await state.update_data(candidate_answers=candidate_answers)

    questions_count = len(state_data['test'])
    if (questions_count - 1) == current_question_number:
        await message.answer('Тестирование окончено!👍 Спасибо за уделенное нам время!😊✌️')
        await state.update_data(end_date=datetime.now())
        candidate_id = (await create_candidate(state))['data']['id']
        await state.update_data(candidate_id=candidate_id)
        await send_answers(state)
        await CandidateScreening.waiting_for_resume.set()
        await state.update_data(test=[], candidate_answers=[], available_vacancies=[])
        await message.answer('Если хочешь еще получить еще выборку вакансий, отправь нам резюме📨')
        return

    current_question_number += 1
    state_data['current_question'] = current_question_number
    question = state_data['test'][current_question_number]
    answers_keys = build_answers_buttons([answer['text'] for answer in question['answers']])
    await state.update_data(current_question=current_question_number)
    await message.answer(question['text'], reply_markup=answers_keys)


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
