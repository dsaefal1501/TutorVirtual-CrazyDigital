using UnityEngine;
using System.Collections;
using System.Collections.Generic;

public class TutorController : MonoBehaviour
{
	private Animator anim;

	[Header("Configuración de Parpadeo")]
	public float esperaMinima = 2f;
	public float esperaMaxima = 5f;
	public string nombreAnimacionBlink = "Blink"; 

	[Header("Configuración de Habla")]
	public string paramHablar = "Talk"; 

	// Diccionario para guardar el último estado ESTÁTICO de cada capa
	private Dictionary<int, string> lastStaticState = new Dictionary<int, string>();

	// Corutinas activas por capa (para poder cancelarlas si llega otra orden)
	private Dictionary<int, Coroutine> activeCoroutines = new Dictionary<int, Coroutine>();

	void Start()
	{
		anim = GetComponent<Animator>();
		
		// Inicializar estados estáticos por defecto (Idle con manos en Jarra)
		lastStaticState[AnimationsReference.BrowsLayerIndex] = AnimationsReference.Brows.None;
		
		// DEFAULT: Manos en Jarra para evitar que se quede 'colgado' o en Empty
		string defL = AnimationsReference.LHand.LHandJarra;
		string defR = AnimationsReference.RHand.RHandJarra;

		lastStaticState[AnimationsReference.LHandLayerIndex] = defL;
		lastStaticState[AnimationsReference.RHandLayerIndex] = defR;

		// Aplicar inmediatamente para que empiece así
		if (anim != null) 
		{
			anim.Play(defL, AnimationsReference.LHandLayerIndex);
			anim.Play(defR, AnimationsReference.RHandLayerIndex);
		}

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

	public void SetExpression(string tag)
	{
		if (anim == null) return;
		tag = tag.Trim();

		string animationName = "";
		int layerIndex = -1;
		bool isDynamic = false;

		// --- 1. CEJAS (Brows) ---
		// --- 1. CEJAS (Brows) ---
		// CEJAS DINÁMICAS: Suben un momento y bajan solas
		if (tag == "[UpBrows]") { animationName = AnimationsReference.Brows.UpBrows; layerIndex = AnimationsReference.BrowsLayerIndex; isDynamic = true; }
		else if (tag == "[RBrowUp]") { animationName = AnimationsReference.Brows.RBrowUp; layerIndex = AnimationsReference.BrowsLayerIndex; isDynamic = true; }
		else if (tag == "[LBrowUp]") { animationName = AnimationsReference.Brows.LBrowUp; layerIndex = AnimationsReference.BrowsLayerIndex; isDynamic = true; }
		// CEJAS ESTÁTICAS (Reset manual o estado base)
		else if (tag == "[NoneBrows]") { animationName = AnimationsReference.Brows.None; layerIndex = AnimationsReference.BrowsLayerIndex; isDynamic = false; }

		// --- 2. MANO IZQUIERDA (LHand) ---
		else if (System.Array.Exists(AnimationsReference.LHand.Dinamicos, x => tag == $"[{x}]")) 
		{ 
			animationName = tag.Trim('[', ']'); layerIndex = AnimationsReference.LHandLayerIndex; isDynamic = true; 
		}
		else if (System.Array.Exists(AnimationsReference.LHand.Estaticos, x => tag == $"[{x}]"))
		{ 
			animationName = tag.Trim('[', ']'); layerIndex = AnimationsReference.LHandLayerIndex; isDynamic = false;
		}

		// --- 3. MANO DERECHA (RHand) ---
		else if (System.Array.Exists(AnimationsReference.RHand.Dinamicos, x => tag == $"[{x}]"))
		{
			animationName = tag.Trim('[', ']'); layerIndex = AnimationsReference.RHandLayerIndex; isDynamic = true;
		}
		else if (System.Array.Exists(AnimationsReference.RHand.Estaticos, x => tag == $"[{x}]"))
		{
			string cleaned = tag.Trim('[', ']');
			if (tag == "[RHandJarra]") cleaned = AnimationsReference.RHand.RHandJarra;
			animationName = cleaned; layerIndex = AnimationsReference.RHandLayerIndex; isDynamic = false;
		}


		// EJECUCIÓN LÓGICA GENERAL
		if (!string.IsNullOrEmpty(animationName) && layerIndex >= 0)
		{
			// A) GESTIÓN DE CORUTINAS (Cancelar reset pendiente si llega nueva orden a la misma capa)
			if (activeCoroutines.ContainsKey(layerIndex) && activeCoroutines[layerIndex] != null)
			{
				StopCoroutine(activeCoroutines[layerIndex]);
				activeCoroutines[layerIndex] = null;
			}

			// B) APLICAR ANIMACIÓN PRINCIPAL
			if (isDynamic)
			{
				// Reproducir dyn y luego volver al último estático
				anim.CrossFade(animationName, 0.2f, layerIndex);
				activeCoroutines[layerIndex] = StartCoroutine(ResetToStaticAfterDelay(layerIndex, 2.5f)); 
			}
			else
			{
				// Es un nuevo estado ESTÁTICO. 
				// AQUÍ APLICAMOS LA LÓGICA DE SIMETRÍA (Igualar manos)
				
				ApplyStaticPoseSymmetry(layerIndex, animationName);
			}
		}
	}

	// Método helper para forzar simetría en poses estáticas (Jarra/Crossed)
	private void ApplyStaticPoseSymmetry(int primaryLayer, string primaryAnimName)
	{
		// 1. Aplicar a la mano principal
		lastStaticState[primaryLayer] = primaryAnimName;
		anim.CrossFade(primaryAnimName, 0.25f, primaryLayer);

		// 2. Determinar la mano "espejo" y la animación correspondiente
		int mirrorLayer = -1;
		string mirrorAnimName = "";

		// Caso: Mano Izquierda manda -> Afecta Derecha
		if (primaryLayer == AnimationsReference.LHandLayerIndex)
		{
			mirrorLayer = AnimationsReference.RHandLayerIndex;
			if (primaryAnimName == AnimationsReference.LHand.LHandJarra) mirrorAnimName = AnimationsReference.RHand.RHandJarra;
			else if (primaryAnimName == AnimationsReference.LHand.LHandCrossed) mirrorAnimName = AnimationsReference.RHand.RHandCrossed;
		}
		// Caso: Mano Derecha manda -> Afecta Izquierda
		else if (primaryLayer == AnimationsReference.RHandLayerIndex)
		{
			mirrorLayer = AnimationsReference.LHandLayerIndex;
			if (primaryAnimName == AnimationsReference.RHand.RHandJarra) mirrorAnimName = AnimationsReference.LHand.LHandJarra;
			else if (primaryAnimName == AnimationsReference.RHand.RHandCrossed) mirrorAnimName = AnimationsReference.LHand.LHandCrossed;
		}

		// 3. Aplicar a la mano espejo si encontramos correspondencia
		if (mirrorLayer != -1 && !string.IsNullOrEmpty(mirrorAnimName))
		{
			// Cancelar corutinas en la mano espejo también (para que no vuelva a un estado viejo)
			if (activeCoroutines.ContainsKey(mirrorLayer) && activeCoroutines[mirrorLayer] != null)
			{
				StopCoroutine(activeCoroutines[mirrorLayer]);
				activeCoroutines[mirrorLayer] = null;
			}

			// Actualizar estado y animar
			lastStaticState[mirrorLayer] = mirrorAnimName;
			anim.CrossFade(mirrorAnimName, 0.25f, mirrorLayer);
			// Debug.Log($"[Symmetry] Forzando {mirrorAnimName} en capa {mirrorLayer} por coherencia.");
		}
	}

	IEnumerator ResetToStaticAfterDelay(int layerIndex, float delay)
	{
		yield return new WaitForSeconds(delay);
		
		// Recuperar el último estado estático conocido
		if (lastStaticState.ContainsKey(layerIndex))
		{
			string staticState = lastStaticState[layerIndex];
			if (!string.IsNullOrEmpty(staticState))
			{
				anim.CrossFade(staticState, 0.5f, layerIndex);
			}
		}
		activeCoroutines[layerIndex] = null;
	}

	IEnumerator CicloAnimacionAleatoria()
	{
		while (true)
		{
			float tiempoEspera = Random.Range(esperaMinima, esperaMaxima);
			yield return new WaitForSeconds(tiempoEspera);

			if (anim != null)
			{
				anim.Play(nombreAnimacionBlink, -1, 0f);
			}
		}
	}
}