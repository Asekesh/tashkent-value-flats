from aiogram.fsm.state import State, StatesGroup


class NewAlert(StatesGroup):
    districts = State()
    rooms = State()
    price = State()
    area = State()
    floor = State()
    discount = State()
    name = State()


class Feedback(StatesGroup):
    kind = State()
    text = State()
