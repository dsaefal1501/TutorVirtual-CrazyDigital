using UnityEngine;
using System.Collections;
using TMPro;

public class TutorController : MonoBehaviour
{
	private Animator anim;
	private string lastText = "";

	[Header("Configuración de Parpadeo")]
	public float esperaMinima = 2f;
	public float esperaMaxima = 5f;
	public string nombreAnimacionBlink = "Blink"; 

	[Header("Configuracion de Expresiones (Nombres de Estados en Animator)")]
	public string HappyExpressionAnimation;
	public string NeutralExpressionAnimation; 
	public string AngryExpressionAnimation; 
	public string ThinkingExpressionAnimation;
	public string AleteoManosAnimation;
	public string RascarBarbillaAnimation;
    
	[Header("Front Conection")]
	public string ActualLine;

	[Header("Configuración de Habla")]
	public string paramHablar = "Talk"; 
	[SerializeField] private TMP_InputField expressionsField;

	void Start()
	{
		anim = GetComponent<Animator>();
        
		if (expressionsField == null)
		{
			Debug.LogError("Por favor, asigna el TMP_InputField en el Inspector.");
		}

		StartCoroutine(CicloAnimacionAleatoria());
	}

	protected void Update()
	{
		ExpressionManager();
	}

	public void SetTalkingState(int estado)
	{
		if (anim != null)
		{
			bool estaHablando = (estado == 1);
			anim.SetBool(paramHablar, estaHablando);
		}
	}
    
	public void SetActualLine(string line)
	{
        
	}

	public void ExpressionManager()
	{
		if (expressionsField == null) return;

		if (expressionsField.text == lastText) return;
		lastText = expressionsField.text;

		var (estadoAActivar, capaObjetivo) = lastText switch
		{
			var t when t.Contains("[Happy]")            => (HappyExpressionAnimation, 3),
			var t when t.Contains("[Neutral]")          => (NeutralExpressionAnimation, 3),
			var t when t.Contains("[Angry]")            => (AngryExpressionAnimation, 3),
			var t when t.Contains("[Thinking]")         => (ThinkingExpressionAnimation, 3),
			var t when t.Contains("[RascarBarbilla]")   => (RascarBarbillaAnimation, 0),
			var t when t.Contains("[AletearManos]")     => (AleteoManosAnimation, 0),
			_                                           => (null, -1)
		};

		if (!string.IsNullOrEmpty(estadoAActivar) && capaObjetivo != -1 && anim.layerCount > capaObjetivo)
		{
			anim.CrossFade(estadoAActivar, 0.2f, capaObjetivo);
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
				if (!anim.GetBool(paramHablar))
				{
					anim.Play(nombreAnimacionBlink);
				}
			}
		}
	}
}