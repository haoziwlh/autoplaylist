class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/5b/82/f58c3d6aabaa1f477aaec3612921397aab78d5395d4123c48a4237041875/myplaylist-0.3.3-py3-none-any.whl",,,,,
      using: :nounzip
  sha256 "aaf495bdd55e5529f3a6d7414aaa0bd231ef36da33e11fe2511616b8772cf0d3"
  license "MIT"

  depends_on "python@3.11"
  depends_on "mpv"

  def install
    venv = libexec/"venv"
    system Formula["python@3.11"].opt_bin/"python3.11", "-m", "venv", venv
    system venv/"bin/pip", "install", "myplaylist==#{version}"
    bin.install_symlink venv/"bin/myplaylist"
  end

  test do
    assert_match "myplaylist", shell_output("#{bin}/myplaylist --help")
  end
end
