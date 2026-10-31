// Passages to read aloud when recording a voice: about 30 to 45 seconds each at a natural pace.
// Pure module (no DOM). Languages without a passage fall back to English (see `readingText`).

/** @type {Record<string, string>} */
export const READING_TEXTS = {
  en:
    "Every morning I take the same path along the river. In spring the water is fast and " +
    "loud, and in summer it slows down and turns a deep green. Some days I stop on the old " +
    "stone bridge and watch the boats go by. A neighbour once told me that the bridge is " +
    "more than two hundred years old. I like to think about everyone who has crossed it " +
    "before me, each with their own plans for the day. Then I walk on, a little slower than " +
    "before, and the city slowly wakes up around me.",
  es:
    "Cada mañana tomo el mismo camino junto al río. En primavera el agua corre rápida y " +
    "ruidosa, y en verano se calma y se vuelve de un verde profundo. Algunos días me detengo " +
    "en el viejo puente de piedra y miro pasar los barcos. Una vecina me contó que el puente " +
    "tiene más de doscientos años. Me gusta pensar en todas las personas que lo han cruzado " +
    "antes que yo, cada una con sus propios planes. Luego sigo caminando, un poco más despacio, " +
    "mientras la ciudad se despierta a mi alrededor.",
  fr:
    "Chaque matin, je prends le même chemin le long de la rivière. Au printemps, l'eau est " +
    "rapide et bruyante, et en été elle ralentit et prend une couleur vert profond. Certains " +
    "jours, je m'arrête sur le vieux pont de pierre pour regarder passer les bateaux. Un voisin " +
    "m'a dit un jour que ce pont avait plus de deux cents ans. J'aime penser à tous ceux qui " +
    "l'ont traversé avant moi, chacun avec ses projets pour la journée. Puis je reprends ma " +
    "marche, un peu plus lentement, pendant que la ville se réveille autour de moi.",
  de:
    "Jeden Morgen gehe ich denselben Weg am Fluss entlang. Im Frühling ist das Wasser schnell " +
    "und laut, im Sommer wird es ruhiger und tiefgrün. An manchen Tagen bleibe ich auf der " +
    "alten Steinbrücke stehen und schaue den Booten zu. Ein Nachbar hat mir einmal erzählt, " +
    "dass die Brücke über zweihundert Jahre alt ist. Ich denke gern an all die Menschen, die " +
    "sie vor mir überquert haben, jeder mit eigenen Plänen für den Tag. Dann gehe ich weiter, " +
    "etwas langsamer als vorher, und die Stadt erwacht langsam um mich herum.",
  it:
    "Ogni mattina percorro la stessa strada lungo il fiume. In primavera l'acqua è veloce e " +
    "rumorosa, mentre in estate rallenta e diventa di un verde profondo. Alcuni giorni mi " +
    "fermo sul vecchio ponte di pietra a guardare passare le barche. Un vicino una volta mi ha " +
    "detto che il ponte ha più di duecento anni. Mi piace pensare a tutte le persone che lo " +
    "hanno attraversato prima di me, ognuna con i propri programmi. Poi riprendo a camminare, " +
    "un po' più piano, mentre la città si sveglia intorno a me.",
  pt:
    "Todas as manhãs faço o mesmo caminho ao longo do rio. Na primavera a água corre rápida e " +
    "barulhenta, e no verão fica mais calma e de um verde profundo. Alguns dias paro na velha " +
    "ponte de pedra e fico a ver os barcos passar. Um vizinho contou-me uma vez que a ponte " +
    "tem mais de duzentos anos. Gosto de pensar em todas as pessoas que a atravessaram antes " +
    "de mim, cada uma com os seus planos para o dia. Depois continuo a andar, um pouco mais " +
    "devagar, enquanto a cidade acorda à minha volta.",
  nl:
    "Elke ochtend loop ik hetzelfde pad langs de rivier. In de lente stroomt het water snel " +
    "en luid, en in de zomer wordt het rustig en diepgroen. Soms blijf ik staan op de oude " +
    "stenen brug en kijk ik naar de boten. Een buurman vertelde me ooit dat de brug meer dan " +
    "tweehonderd jaar oud is. Ik denk graag aan alle mensen die hem voor mij zijn overgestoken, " +
    "ieder met eigen plannen voor die dag. Daarna loop ik verder, iets langzamer dan eerst, " +
    "terwijl de stad om me heen langzaam wakker wordt.",
  ja:
    "毎朝、私は川沿いの同じ道を歩きます。春になると水の流れは速く、音も大きくなります。" +
    "夏になると流れはゆっくりになり、深い緑色に変わります。ときどき古い石の橋の上で立ち止まり、" +
    "通り過ぎる船を眺めます。近所の人が、この橋は二百年以上前に作られたと教えてくれました。" +
    "これまでにこの橋を渡った、たくさんの人たちのことを考えるのが好きです。" +
    "それから少しゆっくりと歩き出すと、町が少しずつ目を覚ましていきます。",
  ko:
    "매일 아침 나는 강을 따라 같은 길을 걷는다. 봄에는 물살이 빠르고 소리가 크며, 여름이 되면 " +
    "느려지고 짙은 초록색으로 변한다. 어떤 날에는 오래된 돌다리 위에 멈춰 서서 지나가는 배들을 " +
    "바라본다. 한 이웃이 이 다리가 이백 년도 넘었다고 말해 준 적이 있다. 나보다 먼저 이 다리를 " +
    "건넌 수많은 사람들을 떠올리는 것이 좋다. 그리고 조금 더 천천히 다시 걷기 시작하면, 도시가 " +
    "서서히 깨어난다.",
  ru:
    "Каждое утро я иду одной и той же дорогой вдоль реки. Весной вода быстрая и шумная, а " +
    "летом она замедляется и становится тёмно-зелёной. Иногда я останавливаюсь на старом " +
    "каменном мосту и смотрю на проплывающие лодки. Один сосед как-то рассказал мне, что " +
    "этому мосту больше двухсот лет. Мне нравится думать обо всех, кто переходил его до меня, " +
    "и у каждого были свои планы на день. Потом я иду дальше, чуть медленнее, чем раньше, а " +
    "город вокруг понемногу просыпается.",
};

/**
 * The passage for `code`, or the English one with `fallback: true` when there is none.
 * @param {string} code a language code from /v1/languages
 * @returns {{text: string, language: string, fallback: boolean}}
 */
export function readingText(code) {
  if (Object.hasOwn(READING_TEXTS, code)) {
    return { text: READING_TEXTS[code], language: code, fallback: false };
  }
  return { text: READING_TEXTS.en, language: "en", fallback: true };
}
