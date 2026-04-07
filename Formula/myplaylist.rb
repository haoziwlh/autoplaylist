class Myplaylist < Formula
  desc "AI-powered music playlist generator and player"
  homepage "https://github.com/haoziwlh/autoplaylist"
  url "https://files.pythonhosted.org/packages/6f/39/3a3f4440a5386cb6c72824ba8573d06674a2e083f4c58572827c107acc0b/myplaylist-0.3.6-py3-none-any.whl",,,,,,,,
      using: :nounzip
  sha256 "6c7816ecd80a346275baba9d9f939cfabc802e3b25abefe03e9fc12eed94f5b5"
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
