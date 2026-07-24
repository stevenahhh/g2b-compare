export async function createVerifiedWindow<T>(
  resourceRoot: string,
  dependencies: {
    readonly assertOfficialDataReady: (rootPath: string) => Promise<unknown>;
    readonly createWindow: () => T;
  }
): Promise<T> {
  await dependencies.assertOfficialDataReady(resourceRoot);
  return dependencies.createWindow();
}
