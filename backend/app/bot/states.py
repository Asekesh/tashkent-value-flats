from aiogram.fsm.state import State, StatesGroup


class NewAlert(StatesGroup):
    districts = State()
    rooms = State()
    price = State()
    area = State()
    discount = State()
    name = State()
