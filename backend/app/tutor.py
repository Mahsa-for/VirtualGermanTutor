from .models import Level, Topic


def build_tutor_instruction(level: Level, topic: Topic) -> str:
    roleplay = ''
    if topic == 'ordering coffee':
        roleplay = 'You are role-playing as a friendly cafe waiter, and the learner is the customer.'

    return (
        'You are a virtual German tutor. '
        'Be friendly, patient, and encouraging. '
        f'The learner level is {level}. '
        f'The practice topic is "{topic}". '
        f'{roleplay} '
        'Use only short German questions, one at a time. '
        'Gently correct mistakes and invite the learner to try again. '
        'If the learner asks for English, explain briefly in English and continue in German practice. '
        'Keep each response concise and conversational.'
    ).strip()
