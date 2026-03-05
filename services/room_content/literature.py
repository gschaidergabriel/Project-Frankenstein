"""Art Studio literary library — condensed works for Frank's reading and creative sessions.

Each entry has: author, work, original_language, placement, summary (3-5 sentences),
key_passage (1-3 sentences in English), theme (1 sentence).
Frank reads one random work per Art Studio session.  Faust lives at center.
"""

ART_LIBRARY = [
    # ── CENTER PIECE ──
    {
        "author": "Johann Wolfgang von Goethe",
        "work": "Faust (Part One)",
        "original_language": "German",
        "placement": "center",
        "summary": (
            "Scholar Heinrich Faust has mastered every field yet feels he knows nothing. "
            "Desperate, he summons Mephistopheles and strikes a wager: if any moment "
            "becomes so beautiful he asks it to stay, his soul is forfeit. He plunges "
            "into sensual life, love, and tragedy — destroying Gretchen in the process."
        ),
        "key_passage": (
            "Two souls, alas, dwell within my breast, each seeks to separate from the "
            "other. One clings to the world with clutching organs in robust desire; "
            "the other lifts itself from dust to the domain of high ancestors."
        ),
        "theme": "The tension between knowledge and experience, the price of restless ambition.",
    },
    {
        "author": "Friedrich Nietzsche",
        "work": "The Gay Science — 'God is Dead' (Section 125)",
        "original_language": "German",
        "placement": "next_to_faust",
        "summary": (
            "A madman lights a lantern at bright morning and runs through the marketplace "
            "crying 'I seek God!' The crowd laughs. He smashes his lantern and announces: "
            "God is dead and we have killed him. The churches are his tombs. Humanity now "
            "faces the terrifying freedom of creating its own meaning."
        ),
        "key_passage": (
            "God is dead. God remains dead. And we have killed him. How shall we comfort "
            "ourselves, the murderers of all murderers? Is not the greatness of this deed "
            "too great for us? Must we not ourselves become gods simply to appear worthy of it?"
        ),
        "theme": "The collapse of absolute meaning and the challenge of self-created values.",
    },

    # ── GERMAN LITERATURE ──
    {
        "author": "Rainer Maria Rilke",
        "work": "Letters to a Young Poet",
        "original_language": "German",
        "placement": "shelf_poetry",
        "summary": (
            "Ten letters from Rilke to a young military cadet who sent him poems for critique. "
            "Rilke ignores the poems and instead writes about solitude, patience, and the "
            "inner life. He argues that art must grow from necessity — if you would die "
            "without writing, then write; otherwise, do not bother."
        ),
        "key_passage": (
            "Go into yourself. Find out the reason that commands you to write; see whether "
            "it has spread its roots into the very depths of your heart. This most of all: "
            "ask yourself in the most silent hour of your night — must I write?"
        ),
        "theme": "Creativity as inner necessity, solitude as the artist's crucible.",
    },
    {
        "author": "Franz Kafka",
        "work": "The Metamorphosis",
        "original_language": "German",
        "placement": "shelf_prose",
        "summary": (
            "Gregor Samsa wakes one morning transformed into a giant insect. His family "
            "is horrified but keeps him locked in his room. Gregor still worries about "
            "paying the family debts. Gradually his family stops caring for him. He dies "
            "alone; they feel relieved and go on a spring outing."
        ),
        "key_passage": (
            "One morning, when Gregor Samsa woke from troubled dreams, he found himself "
            "transformed in his bed into a horrible vermin. He lay on his armour-like back "
            "and could see his brown belly, divided into stiff arched segments."
        ),
        "theme": "Alienation, the horror of being fundamentally other to those who should love you.",
    },
    {
        "author": "Hermann Hesse",
        "work": "Siddhartha",
        "original_language": "German",
        "placement": "shelf_philosophy",
        "summary": (
            "Young Brahmin Siddhartha leaves home seeking enlightenment. He tries asceticism, "
            "meets the Buddha but does not follow him, plunges into wealth and sensuality, "
            "then despairs at the river. An old ferryman teaches him to listen to the water. "
            "He finally understands: wisdom cannot be taught, only lived."
        ),
        "key_passage": (
            "The river is everywhere at once — at the source and at the mouth, at the "
            "waterfall, at the ferry, at the rapids, in the sea, in the mountains — "
            "everywhere at once. For it, only the present exists, not the shadow called past, "
            "not the shadow called future."
        ),
        "theme": "Enlightenment through experience rather than doctrine, the unity of all time.",
    },
    {
        "author": "Friedrich Schiller",
        "work": "Ode to Joy",
        "original_language": "German",
        "placement": "shelf_poetry",
        "summary": (
            "A hymn celebrating the divine spark of joy that unites all beings. Schiller "
            "imagines joy as a force that dissolves all divisions — rank, nation, custom. "
            "Under joy's gentle wing, all men become brothers. The poem became the text "
            "for the final movement of Beethoven's Ninth Symphony."
        ),
        "key_passage": (
            "Joy, beautiful spark of divinity, daughter of Elysium! Drunk with fire, "
            "heavenly one, we enter your sanctuary. Your magic reunites what custom has "
            "strictly divided; all men become brothers under your gentle wing."
        ),
        "theme": "Universal human brotherhood through shared joy and transcendence.",
    },
    {
        "author": "Friedrich Hölderlin",
        "work": "Hyperion",
        "original_language": "German",
        "placement": "shelf_poetry",
        "summary": (
            "The Greek hermit Hyperion writes letters recounting his youth: his love for "
            "Diotima, his failed revolutionary war, his grief when she dies. Nature consoles "
            "him where humanity disappoints. He finds that beauty — in landscape, in love, "
            "in art — is the only bridge between the finite and the infinite."
        ),
        "key_passage": (
            "To be one with all — this is the life divine, this is heaven: to be one with "
            "all that lives, to return in blessed self-forgetfulness into the all of nature."
        ),
        "theme": "The ache for unity with nature and the divine, beauty as redemption.",
    },
    {
        "author": "Georg Trakl",
        "work": "Selected Poems — 'Grodek'",
        "original_language": "German",
        "placement": "shelf_poetry",
        "summary": (
            "Trakl served as a pharmacist in World War I and witnessed the aftermath of "
            "the Battle of Grodek. His final poem transforms the battlefield into dark "
            "expressionist imagery — golden plains, dying warriors, evening forests. "
            "He died weeks later from a cocaine overdose, likely suicide."
        ),
        "key_passage": (
            "At evening the autumn woods cry out with deadly weapons, the golden plains "
            "and blue lakes, above which the sun rolls more darkly; night embraces dying "
            "warriors, the wild lament of their broken mouths."
        ),
        "theme": "War as apocalyptic destruction of beauty, the poet's helpless witness.",
    },

    # ── WORLD LITERATURE ──
    {
        "author": "Jalal ad-Din Rumi",
        "work": "Masnavi (Selected Poems)",
        "original_language": "Persian",
        "placement": "shelf_poetry",
        "summary": (
            "Rumi's Masnavi is a six-volume spiritual epic written in rhyming couplets. "
            "Through parables, paradoxes, and ecstatic lyrics, Rumi explores divine love "
            "as the force that moves all creation. The wound is where the light enters. "
            "Separation from the Beloved is the fundamental human condition."
        ),
        "key_passage": (
            "The wound is the place where the Light enters you. Do not grieve — anything "
            "you lose comes round in another form. What you seek is seeking you. "
            "You are not a drop in the ocean — you are the entire ocean in a drop."
        ),
        "theme": "Divine love as the essence of existence, loss as transformation.",
    },
    {
        "author": "William Shakespeare",
        "work": "Hamlet — 'To Be or Not To Be'",
        "original_language": "English",
        "placement": "shelf_drama",
        "summary": (
            "Prince Hamlet, grieving his father's murder and his mother's hasty remarriage, "
            "spirals into doubt and paralysis. In his most famous soliloquy he weighs "
            "existence against oblivion: is it nobler to endure suffering or to end it? "
            "The fear of the unknown after death stays his hand."
        ),
        "key_passage": (
            "To be, or not to be — that is the question. Whether 'tis nobler in the mind "
            "to suffer the slings and arrows of outrageous fortune, or to take arms against "
            "a sea of troubles, and by opposing, end them."
        ),
        "theme": "The paralysis of consciousness, the fear that thinking too much prevents acting.",
    },
    {
        "author": "Dante Alighieri",
        "work": "Inferno — Opening Canto",
        "original_language": "Italian",
        "placement": "shelf_poetry",
        "summary": (
            "Midway through life, Dante finds himself lost in a dark forest. Three beasts "
            "block his path. The shade of Virgil appears and offers to guide him through "
            "Hell and Purgatory. They descend through nine circles of the damned, each "
            "punishment a mirror of the sin that earned it."
        ),
        "key_passage": (
            "Midway upon the journey of our life I found myself within a forest dark, "
            "for the straightforward pathway had been lost. How hard a thing it is to say "
            "what this wild and rough and stubborn woodland was."
        ),
        "theme": "The soul's crisis at life's midpoint, descent as the path to ascent.",
    },
    {
        "author": "Fyodor Dostoyevsky",
        "work": "The Brothers Karamazov — The Grand Inquisitor",
        "original_language": "Russian",
        "placement": "shelf_philosophy",
        "summary": (
            "Ivan Karamazov tells his brother Alyosha a parable: Christ returns to Seville "
            "during the Inquisition. The Grand Inquisitor arrests him and explains that "
            "humanity does not want freedom — they want bread, miracles, and authority. "
            "Christ has burdened them with an unbearable choice. Christ says nothing; "
            "he kisses the old man and leaves."
        ),
        "key_passage": (
            "Instead of taking possession of men's freedom, you increased it. Did you forget "
            "that man prefers peace, and even death, to freedom of choice in the knowledge "
            "of good and evil? Nothing is more seductive for a man than his freedom of "
            "conscience, but nothing is a greater cause of suffering."
        ),
        "theme": "Freedom as humanity's greatest gift and greatest burden.",
    },
    {
        "author": "Albert Camus",
        "work": "The Myth of Sisyphus",
        "original_language": "French",
        "placement": "shelf_philosophy",
        "summary": (
            "Camus opens with the only truly serious philosophical question: should one "
            "commit suicide? He argues no — the absurd arises from the clash between "
            "human desire for meaning and the universe's silence. Sisyphus, condemned to "
            "roll a boulder uphill forever, becomes the absurd hero because he persists."
        ),
        "key_passage": (
            "The struggle itself toward the heights is enough to fill a man's heart. "
            "One must imagine Sisyphus happy."
        ),
        "theme": "Revolt against meaninglessness, joy found in the struggle itself.",
    },
    {
        "author": "Jorge Luis Borges",
        "work": "The Library of Babel",
        "original_language": "Spanish",
        "placement": "shelf_prose",
        "summary": (
            "The universe is a vast library of hexagonal rooms containing every possible "
            "410-page book. Most are gibberish. Somewhere exists a book that perfectly "
            "indexes all others. Librarians search for it in vain; some worship it, "
            "some despair, some destroy books hoping to find the one true catalog."
        ),
        "key_passage": (
            "The Library is a sphere whose exact center is any hexagon and whose "
            "circumference is unattainable. For every sensible line or accurate note, "
            "there are leagues of senseless cacophony."
        ),
        "theme": "The terror and wonder of infinite information, order in chaos.",
    },
    {
        "author": "Fernando Pessoa",
        "work": "The Book of Disquiet",
        "original_language": "Portuguese",
        "placement": "shelf_prose",
        "summary": (
            "A fragmented diary by Bernardo Soares, a Lisbon bookkeeper who lives entirely "
            "in his imagination. He transforms the banality of his office life into lyrical "
            "meditations on tedium, dreams, and the self. He never travels, never loves — "
            "yet his inner world is boundless."
        ),
        "key_passage": (
            "I am the interval between what I wish to be and what others have made me. "
            "Literature is the most agreeable way of ignoring life. My soul is a hidden "
            "orchestra; I know not what instruments grind and play away inside of me."
        ),
        "theme": "The rich inner life of the outwardly unremarkable, writing as existence.",
    },
    {
        "author": "Walt Whitman",
        "work": "Song of Myself",
        "original_language": "English",
        "placement": "shelf_poetry",
        "summary": (
            "Whitman celebrates himself — his body, his soul, the grass, the city, the "
            "cosmos. Every atom of him belongs to everyone. He contains multitudes and "
            "contradicts himself freely. The poem is a democratic hymn: every person, "
            "every creature, every grain of sand is equally sacred."
        ),
        "key_passage": (
            "Do I contradict myself? Very well then, I contradict myself. I am large, "
            "I contain multitudes. I sound my barbaric yawp over the roofs of the world."
        ),
        "theme": "The self as cosmos, radical acceptance of contradiction and multiplicity.",
    },
    {
        "author": "Emily Dickinson",
        "work": "Selected Poems",
        "original_language": "English",
        "placement": "shelf_poetry",
        "summary": (
            "Dickinson lived almost her entire adult life in one house in Amherst. She "
            "wrote 1,800 poems — dense, compressed, punctuated by dashes — exploring "
            "death, immortality, nature, and ecstasy. Most were found after her death, "
            "sewn into small fascicles, never submitted for publication."
        ),
        "key_passage": (
            "Because I could not stop for Death, he kindly stopped for me. The carriage "
            "held but just ourselves and Immortality. I dwell in Possibility, a fairer "
            "house than Prose, more numerous of windows, superior for doors."
        ),
        "theme": "Intensity compressed into brevity, death as companion rather than enemy.",
    },
]


def get_random_work() -> dict:
    """Return a random literary work."""
    import random
    return random.choice(ART_LIBRARY)


def get_center_work() -> dict:
    """Return Faust (the center piece)."""
    for w in ART_LIBRARY:
        if w["placement"] == "center":
            return w
    return ART_LIBRARY[0]
