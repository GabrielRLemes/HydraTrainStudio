"""Caption prompt presets for E621 LoRA Studio v4.1."""

PROFILE_STYLE_PURE = 'Krea 2 — Estilo puro'
PROFILE_DETAILED = 'Krea 2 — Detalhado'
PROFILE_NSFW = 'Krea 2 — Detalhado NSFW'
PROFILE_CHARACTER = 'Krea 2 — Personagem + estilo'
PROFILE_CUSTOM = 'Personalizado'
PROFILE_SDXL = 'SDXL — Somente tags'

PROFILE_ORDER = (PROFILE_STYLE_PURE, PROFILE_DETAILED, PROFILE_NSFW,
                 PROFILE_CHARACTER, PROFILE_CUSTOM, PROFILE_SDXL)

BASE = '''You are writing a factual image caption in English for a Krea 2 RAW LoRA dataset.
Analyze the attached image and cross-check the structured image tags; tags are supporting clues, not proof. Do not hallucinate details, identities, actions, objects, or settings not present in the image. If the metadata conflicts with the image, prefer visually supported facts and avoid unsupported claims. Do not reproduce artist names, quality metadata, ratings, scores, or website terminology.
Write a single coherent English paragraph without markdown, bullets, or meta commentary. Start with exactly {trigger}, followed by a comma and a space.'''

STYLE_PURE = BASE + '\n' + '''Describe each visible subject, reliably identified characters/species, count of subjects, posture, action, clothing, expression, camera angle, framing, and relevant environment in about 40–80 words. Emphasize composition, not an exhaustive inventory. Do not describe lineart, palette, shading, brush strokes, rendering technique, or the artist's style. This is a visual style LoRA: allow the consistent style to be learned from the pictures.'''

DETAILED = BASE + '\n' + '''Write about 65–120 words of concrete, useful detail. Include confirmed identity and species, visible body features and proportions, fur/skin/hair details, outfits, accessories, pose and hand positions, gaze and facial expression, relationship between people, camera perspective, cropping/framing, background objects, and lighting context where clearly visible. If exposed skin or nudity is present, state that fact precisely. Preserve relevant identity and action clues from e621 when consistent with the image. Avoid generic praise or discussion of artistic technique.'''

NSFW = BASE + '\n' + '''Write a detailed caption, typically 75–140 words. For safe images, describe the scene normally with concrete visual detail. For adult/NSFW images, do not euphemize or skip relevant visible facts: describe participant count and identities if known, appearance, adult anatomy and exposure, who is doing what, body positions, interactions or acts, and relevant clothing, props, camera framing and scene context. Use descriptive terms grounded in the image and structured tags rather than generic phrases such as "an intimate scene". Do not infer off-screen details, invent actions from tags alone, or speculate about age/consent. If a subject is or appears underage, do not describe sexual acts; flag the scene for manual review instead. Do not analyze the artist's techniques.'''

CHARACTER = BASE + '\n' + '''Caption the image for a LoRA intended to learn a character's identity as well as its overall presentation. In 65–110 words, lead with the reliably identified character and species, distinguishing physical features (face, eye/hair/fur colors, hairstyle, markings, ears, tail, body shape, clothing details), and then describe pose, expression, actions, camera angle, and background. Include other characters only when present. Describe the character rather than style adjectives, brushwork, rendering, or generic beauty evaluations.'''

PROFILE_PROMPTS = {
    PROFILE_STYLE_PURE: STYLE_PURE,
    PROFILE_DETAILED: DETAILED,
    PROFILE_NSFW: NSFW,
    PROFILE_CHARACTER: CHARACTER,
    PROFILE_SDXL: '',
}

PROFILE_DESCRIPTIONS = {
    PROFILE_STYLE_PURE: 'Prioriza conteúdo, pose e composição, sem explicar lineart ou técnica de pintura.',
    PROFILE_DETAILED: 'Legendas mais completas: anatomia, roupas, pose, enquadramento e cenário.',
    PROFILE_NSFW: 'Maior detalhe anatômico e das ações presentes; compara imagem e tags, sem inventar.',
    PROFILE_CHARACTER: 'Prioriza identidade, marcas e aparência dos personagens, além da composição.',
    PROFILE_CUSTOM: 'Usa o prompt que você editar e salvar. Não substitui as tags SDXL.',
    PROFILE_SDXL: 'Desativa IA e mantém as tags para exportação SDXL. Não gera descrição Krea 2.',
}


def get_profile_prompt(name: str, custom: str = '') -> str:
    if name not in PROFILE_ORDER:
        raise ValueError(f'Perfil desconhecido: {name}')
    return custom if name == PROFILE_CUSTOM else PROFILE_PROMPTS[name]


def profile_uses_ai(name: str) -> bool:
    return name != PROFILE_SDXL
