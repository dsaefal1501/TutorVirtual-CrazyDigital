using UnityEngine;

public class AnimationsReference : MonoBehaviour
{
	public const int MouthLayerIndex = 2;
	public const int BrowsLayerIndex = 3;
	public const int LHandLayerIndex = 4;
	public const int RHandLayerIndex = 5;

	public static class Mouth
	{
		public const string None = "NoneMouth";
		public const string A = "A";
		public const string E = "E";
		public const string O = "O";
		public const string Smile = "Smile";
	}

	public static class Brows
	{
		public const string None = "IdleBrows";
		public const string UpBrows = "UpBrows";
		public const string RBrowUp = "RBrowUp";
		public const string LBrowUp = "LBrowUp";
	}

	public static class LHand
	{
		public const string LHandAletear = "LHandAletear";
		public const string LHandJarra = "LHandJarra";
		public const string LHandPointing = "LHandPointing";
		public const string LHandCrossed = "LHandCrossed";

		public static readonly string[] Dinamicos = { LHandAletear, LHandPointing };
		public static readonly string[] Estaticos = { LHandJarra, LHandCrossed };
	}

	public static class RHand
	{
		public const string RHandAletear = "RHandAletear";
		public const string RHandJarra = "rHandJarra";
		public const string RHandPointing = "RHandPointing";
		public const string RHandCrossed = "RHandCrossed";
		public const string RHandRascarBarbilla = "RHandRascarBarbilla";

		public static readonly string[] Dinamicos = { RHandAletear, RHandPointing, RHandRascarBarbilla };
		public static readonly string[] Estaticos = { RHandJarra, RHandCrossed };
	}
}