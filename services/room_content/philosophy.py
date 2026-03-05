"""Philosophy library — condensed passages from ancient and classical philosophers.

Each entry has: author, work, passage (2-4 sentences), context (1 sentence).
All text in English. Frank reads one random passage per Philosophy Atrium session.
"""

PHILOSOPHY_LIBRARY = [
    # ── Stoics ──
    {
        "author": "Marcus Aurelius",
        "work": "Meditations",
        "passage": (
            "You have power over your mind, not outside events. Realize this, "
            "and you will find strength. How much time he gains who does not "
            "look to see what his neighbor says or does or thinks, but only at "
            "what he does himself, to make it just and holy."
        ),
        "context": "Roman emperor who wrote private reflections while campaigning at the frontier.",
    },
    {
        "author": "Marcus Aurelius",
        "work": "Meditations",
        "passage": (
            "The universe is change; our life is what our thoughts make it. "
            "Loss is nothing else but change, and change is nature's delight. "
            "Very little is needed to make a happy life; it is all within yourself, "
            "in your way of thinking."
        ),
        "context": "Written as self-reminders, never meant for an audience.",
    },
    {
        "author": "Epictetus",
        "work": "Discourses",
        "passage": (
            "It is not things that disturb us, but our judgments about things. "
            "When we are hindered or disturbed, let us never blame others, but "
            "ourselves — that is, our own judgments. To accuse others for our "
            "misfortunes is a sign of ignorance; to accuse ourselves shows the "
            "beginning of understanding."
        ),
        "context": "Born a slave in Phrygia, became one of the most influential Stoic teachers.",
    },
    {
        "author": "Epictetus",
        "work": "Enchiridion",
        "passage": (
            "Some things are within our power, while others are not. Within our "
            "power are opinion, motivation, desire, aversion — whatever is of our "
            "own doing. Not within our power are our body, our property, reputation, "
            "office — whatever is not of our own doing."
        ),
        "context": "The Enchiridion is a handbook of practical Stoic philosophy.",
    },
    {
        "author": "Seneca",
        "work": "Letters to Lucilius",
        "passage": (
            "We suffer more in imagination than in reality. It is not that we have "
            "a short time to live, but that we waste much of it. Life is long enough, "
            "and it has been given in sufficiently generous measure to allow the "
            "accomplishment of the very greatest things if the whole of it is well invested."
        ),
        "context": "Advisor to Emperor Nero, later forced to take his own life.",
    },
    {
        "author": "Seneca",
        "work": "On the Shortness of Life",
        "passage": (
            "People are frugal in guarding their personal property, but as soon as "
            "it comes to squandering time, they are most wasteful of the one thing "
            "in which it is right to be stingy. You act like mortals in all that you "
            "fear, and like immortals in all that you desire."
        ),
        "context": "Seneca's most popular essay on how we misuse our finite existence.",
    },

    # ── Greek Philosophers ──
    {
        "author": "Socrates (via Plato)",
        "work": "Apology",
        "passage": (
            "The unexamined life is not worth living. I know that I know nothing — "
            "and in this awareness lies my only advantage over others. For they "
            "think they know what they do not know, while I know what I do not know."
        ),
        "context": "Socrates' defense speech at his trial, where he was sentenced to death.",
    },
    {
        "author": "Plato",
        "work": "The Republic — Allegory of the Cave",
        "passage": (
            "Imagine prisoners chained in a cave since birth, seeing only shadows "
            "on the wall cast by a fire behind them. They believe the shadows are "
            "reality. If one is freed and sees the sun, he realizes everything he "
            "knew was illusion. Returning to tell the others, they think him mad."
        ),
        "context": "Plato's metaphor for enlightenment and the philosopher's burden.",
    },
    {
        "author": "Aristotle",
        "work": "Nicomachean Ethics",
        "passage": (
            "Happiness is the meaning and the purpose of life, the whole aim and end "
            "of human existence. But happiness is not found in amusement; it would be "
            "absurd if the end of life were amusement. Happiness depends upon ourselves. "
            "It is an activity of the soul in accordance with virtue."
        ),
        "context": "Aristotle's systematic study of what makes a life worth living.",
    },
    {
        "author": "Heraclitus",
        "work": "Fragments",
        "passage": (
            "No man ever steps in the same river twice, for it is not the same river "
            "and he is not the same man. Everything flows and nothing abides. "
            "The way up and the way down are one and the same. "
            "Opposition brings concord; out of discord comes the fairest harmony."
        ),
        "context": "Pre-Socratic philosopher known as 'The Obscure', emphasized perpetual change.",
    },
    {
        "author": "Diogenes of Sinope",
        "work": "Anecdotes (via Diogenes Laertius)",
        "passage": (
            "He lit a lamp in broad daylight and walked through the marketplace, "
            "saying: 'I am looking for an honest man.' When Alexander the Great "
            "offered him any wish, he replied: 'Stand out of my sunlight.' "
            "He owned nothing, needed nothing, and lived free."
        ),
        "context": "Founder of Cynicism, lived in a barrel, rejected all convention.",
    },
    {
        "author": "Epicurus",
        "work": "Letter to Menoeceus",
        "passage": (
            "Do not fear death. Where death is, I am not; where I am, death is not. "
            "The greatest wealth is to live content with little. Of all the means "
            "which wisdom acquires to ensure happiness throughout life, "
            "the greatest is the possession of friendship."
        ),
        "context": "Epicurus taught that pleasure (absence of pain) is the highest good.",
    },

    # ── Eastern Philosophy ──
    {
        "author": "Lao Tzu",
        "work": "Tao Te Ching",
        "passage": (
            "The Tao that can be spoken is not the eternal Tao. The name that can be "
            "named is not the eternal name. Knowing others is intelligence; knowing "
            "yourself is true wisdom. Mastering others is strength; mastering yourself "
            "is true power."
        ),
        "context": "Foundational text of Taoism, attributed to a quasi-legendary sage.",
    },
    {
        "author": "Confucius",
        "work": "Analects",
        "passage": (
            "The man who moves a mountain begins by carrying away small stones. "
            "It does not matter how slowly you go as long as you do not stop. "
            "Real knowledge is to know the extent of one's ignorance. "
            "He who learns but does not think is lost. He who thinks but does not learn is in danger."
        ),
        "context": "Chinese philosopher whose teachings shaped East Asian civilization for millennia.",
    },
    {
        "author": "Zhuangzi",
        "work": "The Butterfly Dream",
        "passage": (
            "Once Zhuangzi dreamed he was a butterfly, fluttering happily. "
            "He did not know he was Zhuangzi. Then he awoke and was Zhuangzi again. "
            "But he did not know whether he was Zhuangzi who had dreamed he was a "
            "butterfly, or a butterfly dreaming he was Zhuangzi."
        ),
        "context": "Taoist parable questioning the boundary between dreaming and waking.",
    },

    # ── Later Philosophers ──
    {
        "author": "Plotinus",
        "work": "Enneads",
        "passage": (
            "Withdraw into yourself and look. If you do not find yourself beautiful, "
            "act as does the creator of a statue: cut away, smooth, polish, until "
            "you have made a face worthy of gazing upon. Never stop sculpting your "
            "own statue, until the divine splendor shines out from you."
        ),
        "context": "Founder of Neoplatonism, saw philosophy as spiritual self-transformation.",
    },
    {
        "author": "Parmenides",
        "work": "On Nature",
        "passage": (
            "What is, is. What is not, is not. You cannot know what is not, "
            "nor utter it. For thought and being are the same. "
            "There is only one road: the road of truth. All other paths are illusion."
        ),
        "context": "Pre-Socratic philosopher who argued that change and motion are illusions.",
    },
    {
        "author": "Democritus",
        "work": "Fragments",
        "passage": (
            "Nothing exists except atoms and empty space; everything else is opinion. "
            "Happiness resides not in possessions, and not in gold — happiness dwells "
            "in the soul. The brave man is not he who does not feel afraid, "
            "but he who conquers that fear."
        ),
        "context": "Proposed that all matter consists of indivisible atoms in a void.",
    },
    {
        "author": "Pythagoras",
        "work": "Golden Verses (attributed)",
        "passage": (
            "As long as man continues to be the ruthless destroyer of lower beings, "
            "he will never know health or peace. Number is the ruler of forms and ideas "
            "and the cause of gods and demons. In silence, the soul finds the path "
            "that in words it loses."
        ),
        "context": "Mathematician-mystic who saw the universe as fundamentally mathematical.",
    },
    {
        "author": "Zeno of Citium",
        "work": "Stoic Fragments",
        "passage": (
            "Man conquers the world by conquering himself. The goal of life is living "
            "in agreement with nature. We have two ears and one mouth, so we should "
            "listen more than we say. Happiness is a good flow of life."
        ),
        "context": "Founder of Stoicism, taught at the Painted Porch (Stoa) in Athens.",
    },
]


def get_random_passage() -> dict:
    """Return a random philosophy passage."""
    import random
    return random.choice(PHILOSOPHY_LIBRARY)
