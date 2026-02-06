from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import random

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Base de datos de ejemplo expandida
banco_preguntas = [
    {
        "pregunta": "¿Cuál es la capital de España?",
        "opciones": ["Madrid", "Barcelona", "Valencia", "Sevilla"],
        "correcta": 0
    },
    {
        "pregunta": "¿Qué planeta es conocido como el Planeta Rojo?",
        "opciones": ["Venus", "Marte", "Júpiter", "Saturno"],
        "correcta": 1
    },
    {
        "pregunta": "¿Cuál es el río más largo del mundo?",
        "opciones": ["Nilo", "Misisipi", "Amazonas", "Yangtsé"],
        "correcta": 2
    },
    {
        "pregunta": "¿Quién escribió 'Don Quijote de la Mancha'?",
        "opciones": ["Federico García Lorca", "Miguel de Cervantes", "Gabriel García Márquez", "Isabel Allende"],
        "correcta": 1
    },
    {
        "pregunta": "¿Cuál es el elemento químico con el símbolo 'O'?",
        "opciones": ["Oro", "Osmio", "Oxígeno", "Hierro"],
        "correcta": 2
    },
    {
        "pregunta": "¿En qué año llegó el ser humano a la Luna?",
        "opciones": ["1965", "1969", "1972", "1959"],
        "correcta": 1
    },
    {
        "pregunta": "¿Cuál es el lenguaje de programación más usado para Inteligencia Artificial?",
        "opciones": ["Java", "C++", "Python", "JavaScript"],
        "correcta": 2
    }
]

@app.get("/examen")
def obtener_examen():
    # Opcional: Mezclar las preguntas para que no salgan siempre igual
    preguntas_aleatorias = random.sample(banco_preguntas, len(banco_preguntas))
    return {"preguntas": preguntas_aleatorias}