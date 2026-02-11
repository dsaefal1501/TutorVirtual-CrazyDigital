using UnityEngine;
using System.Collections;

public class TutorController : MonoBehaviour
{
	private Animator anim;

	[Header("Configuración de Parpadeo")]
	public float esperaMinima = 2f;
	public float esperaMaxima = 5f;
	public string nombreAnimacionBlink = "Blink"; // Nombre del ESTADO en el Animator
	
	[Header("Configuracion de Expresiones")]
	public string HappyExpressionAnimation;
	public string NeutralExpressionAnimation; 
	public string AngryExpressionAnimation; 
	public string ThinkingExpressionAnimation;
	public string Happy, Neutral, Angry, Thinking, Explaining;

	[Header("Configuración de Habla")]
	public string paramHablar = "Talk"; // Nombre del BOOLEAN en el Animator

	void Start()
	{
		anim = GetComponent<Animator>();
        
		// Iniciamos el parpadeo automático
		StartCoroutine(CicloAnimacionAleatoria());
	}

	// --- ESTA FUNCIÓN ES LLAMADA DESDE JAVASCRIPT ---
	// Recibe 1 para activar (True) y 0 para desactivar (False)
	public void SetTalkingState(int estado)
	{
		if (anim != null)
		{
			bool estaHablando = (estado == 1);
			anim.SetBool(paramHablar, estaHablando);
            
			// Opcional: Debug para ver si llega la señal en consola de Unity
			// Debug.Log($"Mensaje recibido desde Web. Hablando: {estaHablando}");
		}
	}

	IEnumerator CicloAnimacionAleatoria()
	{
		while (true)
		{
			float tiempoEspera = Random.Range(esperaMinima, esperaMaxima);
			yield return new WaitForSeconds(tiempoEspera);

			if (anim != null)
			{
				// Solo parpadeamos si el parámetro "Talk" NO está activado
				// para evitar conflictos visuales extraños
				if (!anim.GetBool(paramHablar))
				{
					anim.Play(nombreAnimacionBlink);
				}
			}
		}
	}
}