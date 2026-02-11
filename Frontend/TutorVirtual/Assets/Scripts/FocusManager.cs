using UnityEngine;
using UnityEngine.InputSystem; // Si usas el nuevo Input System
// using UnityEngine; // Si usas el Input Manager clásico (Input.GetKey...)

public class FocusManager : MonoBehaviour
{
	[Header("Arrastra aquí a tu Player")]
	public PlayerInput playerInput; 

	// Esta función será llamada desde JavaScript
	// state = 0 -> Chat Abierto (Bloquear juego)
	// state = 1 -> Chat Cerrado (Permitir juego)
	public void SetInputState(int state)
	{
		bool isGameActive = (state == 1);

		// 1. Desactivar la captura de teclado del navegador (para que puedas escribir tildes, espacios, etc.)
        #if !UNITY_EDITOR && UNITY_WEBGL
		UnityEngine.WebGLInput.captureAllKeyboardInput = isGameActive;
        #endif

		// 2. Desactivar el New Input System del jugador
		if (playerInput != null)
		{
			if (isGameActive)
			{
				playerInput.ActivateInput();
				Debug.Log("Input Reactivado");
			}
			else
			{
				playerInput.DeactivateInput();
				Debug.Log("Input Desactivado (Chat escribiendo)");
			}
		}
	}
}