using UnityEngine;
using System.Collections;

public class TutorController : MonoBehaviour
{
	private Animator anim;

	[Header("Configuración de Parpadeo")]
	public float esperaMinima = 2f;
	public float esperaMaxima = 5f;
	public string nombreAnimacionBlink = "Blink"; 

	[Header("Nombres de Estados en Animator")]
	public string HappyExpressionAnimation = "Happy";
	public string NeutralExpressionAnimation = "Neutral"; 
	public string ThinkingExpressionAnimation = "Thinking";
	public string ExplainingExpressionAnimation = "Talking"; // Para [Explaining]
	public string SurprisedExpressionAnimation = "Surprised";
	public string EncouragingExpressionAnimation = "Encouraging";

	[Header("Configuración de Habla")]
	public string paramHablar = "Talk"; 

	void Start()
	{
		anim = GetComponent<Animator>();
		StartCoroutine(CicloAnimacionAleatoria());
	}

	// JS llamará a esto: window.unityInstance.SendMessage('Tutor', 'SetTalkingState', 1);
	public void SetTalkingState(int estado)
	{
		if (anim != null)
		{
			bool estaHablando = (estado == 1);
			anim.SetBool(paramHablar, estaHablando);
		}
	}

	// JS llamará a esto: window.unityInstance.SendMessage('Tutor', 'SetExpression', '[Happy]');
	public void SetExpression(string tag)
	{
		if (anim == null) return;

		// Limpiamos la etiqueta por si acaso llega con espacios
		tag = tag.Trim();

		string estadoAActivar = null;
		int capaObjetivo = 3; // Asumo que tus expresiones faciales están en la capa 3 (Overrides)

		// Switch moderno de C#
		estadoAActivar = tag switch
		{
			"[Happy]"       => HappyExpressionAnimation,
			"[SuperHappy]"  => HappyExpressionAnimation, // Reusamos si no tienes una Super
			"[Neutral]"     => NeutralExpressionAnimation,
			"[Thinking]"    => ThinkingExpressionAnimation,
			"[Explaining]"  => ExplainingExpressionAnimation,
			"[Surprised]"   => SurprisedExpressionAnimation,
			"[Encouraging]" => EncouragingExpressionAnimation,
			_               => null
		};

		if (!string.IsNullOrEmpty(estadoAActivar))
		{
			// Usamos CrossFade para que la transición entre muecas sea suave (0.2 segundos)
			anim.CrossFade(estadoAActivar, 0.25f, capaObjetivo);
			Debug.Log($"Cambio de expresión a: {estadoAActivar}");
		}
	}

	IEnumerator CicloAnimacionAleatoria()
	{
		while (true)
		{
			// Esperamos un tiempo aleatorio entre parpadeos
			float tiempoEspera = Random.Range(esperaMinima, esperaMaxima);
			yield return new WaitForSeconds(tiempoEspera);

			if (anim != null)
			{
				// ELIMINADO: if (!anim.GetBool(paramHablar))
            
				// Forzamos el parpadeo sin importar si habla o no.
				// El "-1" indica que use la capa por defecto (o la configurada en el animator)
				// El "0f" reinicia la animación desde el principio.
				anim.Play(nombreAnimacionBlink, -1, 0f);
			}
		}
	}
}